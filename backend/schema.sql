-- TranSafe — Complete Supabase Database Schema Initialization SQL
-- Paste and execute this entire script in your Supabase SQL Editor:
-- (Supabase Dashboard -> SQL Editor -> New Query -> Run)

-- ── 1. Create telemetry schema ──────────────────────────────────
CREATE SCHEMA IF NOT EXISTS telemetry;

-- ── 2. Enable pgvector extension ───────────────────────────────
CREATE EXTENSION IF NOT EXISTS vector;

-- ── 3. USERS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    TEXT NOT NULL,
    risk_profile    TEXT NOT NULL DEFAULT 'normal'
                    CHECK (risk_profile IN ('normal', 'elevated', 'high')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── 4. ACCOUNTS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.accounts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_number  TEXT UNIQUE NOT NULL,
    user_id         UUID NOT NULL REFERENCES public.users(id),
    account_type    TEXT NOT NULL DEFAULT 'SAVINGS'
                    CHECK (account_type IN ('SAVINGS', 'CURRENT')),
    balance_myr     NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'frozen', 'closed')),
    frozen_at       TIMESTAMPTZ,
    frozen_by       TEXT,
    frozen_reason   TEXT,
    unfreeze_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_accounts_user_id ON public.accounts (user_id);
CREATE INDEX IF NOT EXISTS idx_accounts_status  ON public.accounts (status);

-- ── 5. TRANSACTIONS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id      TEXT UNIQUE NOT NULL,
    session_id          UUID,
    sender_account      TEXT NOT NULL REFERENCES public.accounts(account_number),
    recipient_account   TEXT NOT NULL,
    recipient_name      TEXT,
    amount_myr          NUMERIC(12, 2) NOT NULL,
    currency            TEXT NOT NULL DEFAULT 'MYR',
    description         TEXT,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'approved', 'frozen',
                            'cooling_off_expired', 'completed', 'rejected'
                        )),
    risk_score          INTEGER CHECK (risk_score BETWEEN 0 AND 100),
    risk_tier           TEXT CHECK (risk_tier IN ('LOW', 'MEDIUM', 'HIGH')),
    case_id             UUID,
    associated_case_id  UUID,
    frozen_at           TIMESTAMPTZ,
    unfreeze_at         TIMESTAMPTZ,
    initiated_at        TIMESTAMPTZ NOT NULL,
    assessed_at         TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_sender
    ON public.transactions (sender_account, initiated_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_status
    ON public.transactions (status);

-- ── 6. FRAUD_CASES ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fraud_cases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL,
    user_id         UUID NOT NULL REFERENCES public.users(id),
    trigger_type    TEXT NOT NULL
                    CHECK (trigger_type IN (
                        'TELEMETRY', 'TRANSACTION', 'CALL', 'PHISHING', 'REPORT'
                    )),
    risk_score      INTEGER CHECK (risk_score BETWEEN 0 AND 100),
    risk_tier       TEXT CHECK (risk_tier IN ('LOW', 'MEDIUM', 'HIGH')),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'approved', 'pending_biometric',
                        'frozen', 'reported', 'reviewed'
                    )),
    action_taken    TEXT,
    xai_report      JSONB,
    transaction_id  UUID REFERENCES public.transactions(id),
    caller_number   TEXT,
    phishing_source TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fraud_cases_user_id
    ON public.fraud_cases (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fraud_cases_risk_tier
    ON public.fraud_cases (risk_tier);
CREATE INDEX IF NOT EXISTS idx_fraud_cases_created_at
    ON public.fraud_cases (created_at DESC);

-- Add foreign key constraint to transactions for associated_case_id
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'fk_transactions_associated_case'
    ) THEN
        ALTER TABLE public.transactions 
            ADD CONSTRAINT fk_transactions_associated_case 
            FOREIGN KEY (associated_case_id) REFERENCES public.fraud_cases(id) ON DELETE SET NULL;
    END IF;
END $$;

-- ── 7. ADMIN_ALERTS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.admin_alerts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID NOT NULL REFERENCES public.fraud_cases(id),
    alert_type      TEXT NOT NULL
                    CHECK (alert_type IN (
                        'HIGH_RISK_FREEZE', 'ACCOUNT_ACTIVITY', 'MANUAL_REPORT'
                    )),
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'reviewed', 'dismissed')),
    details         JSONB,
    admin_note      TEXT,
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_admin_alerts_status
    ON public.admin_alerts (status, created_at DESC);

-- ── 8. CASE_ENTITIES ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.case_entities (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID NOT NULL REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    entity_type     TEXT NOT NULL CHECK (entity_type IN ('PHONE', 'ACCOUNT', 'URL')),
    entity_value    TEXT NOT NULL,
    extracted_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_case_entities_case_id ON public.case_entities (case_id);
CREATE INDEX IF NOT EXISTS idx_case_entities_value ON public.case_entities (entity_value);

-- ── 9. PHISHING_SUBMISSIONS ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.phishing_submissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID REFERENCES public.fraud_cases(id) ON DELETE SET NULL,
    content_type    TEXT NOT NULL CHECK (content_type IN ('TEXT', 'URL', 'IMAGE')),
    raw_content     TEXT,
    extracted_text  TEXT,
    analysis_result JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_phishing_submissions_case_id ON public.phishing_submissions (case_id);

-- ── 10. CALL_TRANSCRIPTS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.call_transcripts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID NOT NULL REFERENCES public.fraud_cases(id) ON DELETE CASCADE,
    speaker         TEXT NOT NULL CHECK (speaker IN ('CALLER', 'AI', 'USER')),
    utterance       TEXT NOT NULL,
    risk_score      INTEGER CHECK (risk_score BETWEEN 0 AND 100),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_transcripts_case_id ON public.call_transcripts (case_id);

-- ── 11. TELEMETRY_EVENTS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS telemetry.telemetry_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    session_id      UUID NOT NULL,
    device_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    event_value     TEXT,
    app_version     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telemetry_user_session
    ON telemetry.telemetry_events (user_id, session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_telemetry_created_at
    ON telemetry.telemetry_events (created_at DESC);

-- ── 12. FRAUD_MEMORY (pgvector) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS public.fraud_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID REFERENCES public.fraud_cases(id) ON DELETE SET NULL,
    fraud_type      TEXT NOT NULL
                    CHECK (fraud_type IN (
                        'macau_scam', 'investment_scam', 'impersonation_scam',
                        'love_scam', 'phishing', 'parcel_scam', 'other'
                    )),
    content         TEXT NOT NULL,
    phone_numbers   TEXT[],
    bank_accounts   TEXT[],
    urls            TEXT[],
    amount_lost_myr NUMERIC(12, 2) DEFAULT 0.00,
    risk_tier       TEXT NOT NULL DEFAULT 'HIGH'
                    CHECK (risk_tier IN ('LOW', 'MEDIUM', 'HIGH')),
    source          TEXT NOT NULL DEFAULT 'user_report'
                    CHECK (source IN ('user_report', 'system_detected')),
    language        TEXT NOT NULL DEFAULT 'en'
                    CHECK (language IN ('en', 'ms')),
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fraud_memory_fraud_type
    ON public.fraud_memory (fraud_type);

CREATE INDEX IF NOT EXISTS idx_fraud_memory_created_at
    ON public.fraud_memory (created_at DESC);

-- ── 13. search_fraud_memory RPC Function ─────────────────────────
CREATE OR REPLACE FUNCTION search_fraud_memory(
    query_embedding vector(768),
    match_threshold FLOAT DEFAULT 0.75,
    match_count     INT   DEFAULT 5
)
RETURNS TABLE (
    id              UUID,
    case_id         UUID,
    fraud_type      TEXT,
    content         TEXT,
    phone_numbers   TEXT[],
    bank_accounts   TEXT[],
    urls            TEXT[],
    amount_lost_myr NUMERIC,
    risk_tier       TEXT,
    source          TEXT,
    similarity      FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        fm.id,
        fm.case_id,
        fm.fraud_type,
        fm.content,
        fm.phone_numbers,
        fm.bank_accounts,
        fm.urls,
        fm.amount_lost_myr,
        fm.risk_tier,
        fm.source,
        1 - (fm.embedding <=> query_embedding) AS similarity
    FROM public.fraud_memory fm
    WHERE 1 - (fm.embedding <=> query_embedding) > match_threshold
    ORDER BY fm.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
