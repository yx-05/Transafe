-- ════════════════════════════════════════════════════════════════════════════
--  TranSafe v2 — Enterprise Layer Migration
--  Ref: doc/transafe_v2/01_upgrade_plan.md §12 (Data model)
--
--  NEW TABLES ONLY. This migration NEVER alters, drops or renames a v1 table.
--  v1 tables (users, accounts, transactions, fraud_cases, admin_alerts,
--  case_entities, phishing_submissions, call_transcripts, telemetry_events,
--  fraud_memory, learned_keywords) are read-only from v2's perspective.
--
--  Vector dimensionality is 768 — matching DashScope text-embedding-v3 as
--  already used by src/db/vector_store.py::embed_text().
--
--  Idempotent: safe to re-run.
-- ════════════════════════════════════════════════════════════════════════════

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ── Entities (resolved graph nodes) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.entities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type   TEXT NOT NULL CHECK (entity_type IN
                      ('PHONE', 'ACCOUNT', 'URL', 'DOMAIN', 'NAME', 'OTHER')),
    value_raw     TEXT NOT NULL,
    value_norm    TEXT NOT NULL,
    first_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    case_count    INT  NOT NULL DEFAULT 0,
    UNIQUE (entity_type, value_norm)
);

CREATE INDEX IF NOT EXISTS idx_entities_value_norm ON public.entities (value_norm);
CREATE INDEX IF NOT EXISTS idx_entities_type       ON public.entities (entity_type);

-- ── Case ↔ entity mentions ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.case_entity_links (
    case_id    UUID NOT NULL REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    entity_id  UUID NOT NULL REFERENCES public.entities(id)    ON DELETE CASCADE,
    source     TEXT NOT NULL DEFAULT 'regex',   -- regex | manual
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (case_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_case_entity_links_entity
    ON public.case_entity_links (entity_id);

-- ── MO fingerprint + narrative embedding ────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.case_mo (
    case_id      UUID PRIMARY KEY REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    fingerprint  JSONB NOT NULL,
    narrative    TEXT  NOT NULL,
    embedding    VECTOR(768),
    extractor    TEXT  NOT NULL DEFAULT 'llm-v1',
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_mo_extracted_at
    ON public.case_mo (extracted_at DESC);

-- ── Case discovery state (§6.4.0 — OBSERVED / unrecognised pattern) ─────────
CREATE TABLE IF NOT EXISTS public.case_discovery_state (
    case_id              UUID PRIMARY KEY REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    state                TEXT NOT NULL DEFAULT 'NORMAL'
                         CHECK (state IN ('NORMAL', 'OBSERVED', 'CLUSTERED')),
    best_campaign_cosine NUMERIC(4,3),   -- NULL = nothing to compare against
    matched_indicators   INT NOT NULL DEFAULT 0,
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_discovery_state_state
    ON public.case_discovery_state (state);

-- ── Fused case-pair links ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.case_links (
    case_a     UUID NOT NULL REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    case_b     UUID NOT NULL REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    score      NUMERIC(4,3) NOT NULL,
    signals    JSONB NOT NULL,   -- {shared_identifier:{...}, narrative:{...}, ...}
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (case_a, case_b),
    CHECK (case_a < case_b)
);

CREATE INDEX IF NOT EXISTS idx_case_links_score ON public.case_links (score DESC);
CREATE INDEX IF NOT EXISTS idx_case_links_case_b ON public.case_links (case_b);

-- ── Campaigns ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.campaigns (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code           TEXT UNIQUE NOT NULL,               -- SCAM-027
    name           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'CANDIDATE'
                   CHECK (status IN ('CANDIDATE', 'PENDING_VALIDATION', 'APPROVED',
                                     'ACTIVE', 'SUPERSEDED', 'ARCHIVED', 'REJECTED')),
    confidence     NUMERIC(4,3) NOT NULL,
    mo_summary     TEXT,
    mo_embedding   VECTOR(768),
    indicators     JSONB NOT NULL DEFAULT '[]',
    case_count     INT NOT NULL DEFAULT 0,
    customer_count INT NOT NULL DEFAULT 0,
    first_seen     TIMESTAMPTZ,
    last_seen      TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by    TEXT,
    approved_at    TIMESTAMPTZ,
    reject_reason  TEXT
);

CREATE INDEX IF NOT EXISTS idx_campaigns_status
    ON public.campaigns (status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.campaign_cases (
    campaign_id   UUID NOT NULL REFERENCES public.campaigns(id)   ON DELETE CASCADE,
    case_id       UUID NOT NULL REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    linkage_score NUMERIC(4,3) NOT NULL,
    joined_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (campaign_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_campaign_cases_case
    ON public.campaign_cases (case_id);

-- ── Artifact registry (two-tier: core | pack) ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.artifacts (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,                       -- phone_agent_core | SCAM-027
    tier             TEXT NOT NULL DEFAULT 'pack'
                     CHECK (tier IN ('core', 'pack')),
    artifact_type    TEXT NOT NULL,
    target_agent     TEXT NOT NULL,
    version          INT  NOT NULL,
    content          TEXT NOT NULL,
    content_json     JSONB,
    campaign_id      UUID REFERENCES public.campaigns(id), -- NULL for core-tier
    source_campaigns JSONB NOT NULL DEFAULT '[]',
    status           TEXT NOT NULL DEFAULT 'DRAFT'
                     CHECK (status IN ('DRAFT', 'PUBLISHED', 'ROLLED_BACK')),
    effectiveness    JSONB,
    created_by       TEXT NOT NULL DEFAULT 'compiler',     -- compiler | generaliser | human
    approved_by      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_tier_status
    ON public.artifacts (tier, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_target_agent
    ON public.artifacts (target_agent);

CREATE TABLE IF NOT EXISTS public.artifact_consumption (
    artifact_id UUID NOT NULL REFERENCES public.artifacts(id) ON DELETE CASCADE,
    agent_name  TEXT NOT NULL,
    consumed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (artifact_id, agent_name)
);

-- ── Nervous-system event stream (drives the live dashboard) ─────────────────
CREATE TABLE IF NOT EXISTS public.ns_events (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    layer      TEXT NOT NULL,   -- sensing|case|discovery|compiler|registry|propagation|exposure
    event_type TEXT NOT NULL,   -- case_ingested|entity_linked|campaign_proposed|...
    severity   TEXT NOT NULL DEFAULT 'info',
    payload    JSONB NOT NULL,
    run_id     UUID             -- groups a demo scenario run
);

CREATE INDEX IF NOT EXISTS idx_ns_events_ts     ON public.ns_events (ts DESC);
CREATE INDEX IF NOT EXISTS idx_ns_events_layer  ON public.ns_events (layer, ts DESC);
CREATE INDEX IF NOT EXISTS idx_ns_events_run_id ON public.ns_events (run_id, id);

-- ── MCP audit ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.mcp_access_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    caller     TEXT NOT NULL,   -- codebuddy | partner_bank | ...
    role       TEXT NOT NULL,
    tool       TEXT NOT NULL,
    params     JSONB,
    latency_ms INT,
    citations  JSONB
);

CREATE INDEX IF NOT EXISTS idx_mcp_access_log_ts ON public.mcp_access_log (ts DESC);

-- ── Evaluation ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.eval_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label        TEXT NOT NULL,        -- 'before-v6' | 'after-v7'
    artifact_ver JSONB NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary      JSONB
);

CREATE TABLE IF NOT EXISTS public.eval_results (
    id         BIGSERIAL PRIMARY KEY,
    run_id     UUID NOT NULL REFERENCES public.eval_runs(id) ON DELETE CASCADE,
    variant_id TEXT NOT NULL,
    is_scam    BOOLEAN NOT NULL,
    detected   BOOLEAN NOT NULL,
    score      INT,
    latency_ms INT
);

CREATE INDEX IF NOT EXISTS idx_eval_results_run ON public.eval_results (run_id);

-- ── Vector indexes (created last; ivfflat needs data to be useful) ──────────
CREATE INDEX IF NOT EXISTS idx_case_mo_embedding
    ON public.case_mo USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_campaigns_mo_embedding
    ON public.campaigns USING ivfflat (mo_embedding vector_cosine_ops) WITH (lists = 100);

-- ── RPC: graph neighbours (used by GraphStore.neighbours) ───────────────────
CREATE OR REPLACE FUNCTION public.graph_neighbours(entity_id UUID, depth INT DEFAULT 1)
RETURNS TABLE (
    id          UUID,
    entity_type TEXT,
    value_norm  TEXT,
    value_raw   TEXT,
    case_count  INT
)
LANGUAGE sql
STABLE
AS $$
    WITH seed_cases AS (
        SELECT cel.case_id
        FROM public.case_entity_links cel
        WHERE cel.entity_id = graph_neighbours.entity_id
    )
    SELECT DISTINCT e.id, e.entity_type, e.value_norm, e.value_raw, e.case_count
    FROM public.entities e
    JOIN public.case_entity_links l ON l.entity_id = e.id
    WHERE l.case_id IN (SELECT case_id FROM seed_cases)
      AND e.id <> graph_neighbours.entity_id;
$$;
