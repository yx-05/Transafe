## Your mission

You are implementing the **TranSafe v2 Enterprise Upgrade** — a fraud intelligence system that detects scam campaigns across multiple victims, compiles them into defense artifacts, and propagates them to AI agents. The full design is in 7 companion documents under `doc/transafe_v2/`. You must read them before writing any code.

**This is a large implementation. Do NOT attempt to do everything in a single thread.** Your first action after reading the docs should be to create a team and spawn sub-agents for parallel work. The sub-agent spawning instructions are in the "How to spin up sub-agents" section below — follow them exactly.

## What exists today (v1 — do NOT rewrite)

TranSafe v1 is a **real-time, multi-agent, per-incident fraud interceptor** for a single consumer. It is a working backend + frontend with:

- **5 LangGraph workers** (telemetry, phone, phishing, financial, research)
- **Groq LLM** with multi-key rotation (`backend/src/agents/llm.py`)
- **768-dim embeddings** via nomic-embed-text (`backend/src/db/vector_store.py`)
- **Supabase** persistence (fraud_cases, call_transcripts, case_entities, etc.)
- **Live call WebSocket** (`backend/src/api/websocket_call.py`)
- **React frontend** at `frontend/transafe/`

**v2 does not rewrite v1. v2 wraps it.** Zero changes to the latency-critical path.

## What you are building (v2 — the enterprise layer)

Six layers, all new code under `backend/src/enterprise/` and `backend/mcp/`:

| Layer | What it does | Key modules |
|---|---|---|
| L1: Sensing | Extract MO fingerprint from each case transcript | `mo_extractor.py` |
| L2: Living Case | Enrich cases with MO + resolved entities + linkage to other cases | `entity_resolver.py`, `graph_store.py` |
| L3: Discovery | Score case pairs, cluster into campaigns, propose candidates | `linkage.py`, `clustering.py`, `discovery.py` |
| L4: Compiler | Turn approved campaigns into versioned, executable defense artifacts | `compiler.py`, `generaliser.py`, `registry.py` |
| L5: Propagation | Push artifacts to workers, collect consumption receipts | `propagation.py` |
| L6: Exposure | MCP gateway + Liaison Agent for external AI systems (CodeBuddy) | `mcp/server.py`, `liaison_agent.py` |

Plus:
- `enterprise/events.py` — ns_events emitter (WebSocket streaming to console)
- `enterprise/evaluation.py` — eval harness with adaptation loop
- `frontend/enterprise/` — new React console (7 screens)
- `migrations/v2_enterprise.sql` — new tables only, v1 untouched

## Critical design decisions (already made — do not relitigate)

1. **LLM provider: DeepSeek** via `langchain-openai` (`ChatOpenAI` with base_url override). NOT Groq for the enterprise layer.
   > **AS BUILT (2026-09):** the migration did not stop at the enterprise layer — v1's workers, `agents/llm.py`, STT and vision all moved to DeepSeek/DashScope too, because China accessibility was a hard requirement. Groq is no longer a dependency of the live path. See `01_upgrade_plan.md` §21.1.
2. **Embeddings: DashScope `text-embedding-v3`** (free tier, works in China). NOT nomic-embed-text for v2. v1 keeps nomic.
   > **AS BUILT:** requested at **768** dims, not 1024 — matching the existing `fraud_memory` pgvector schema and the `vector(768)` columns in §12. See §21.2.
3. **Graph storage: Postgres** behind a `GraphStore` protocol. NOT Neo4j.
4. **MCP transport: stdio** (CodeBuddy supports stdio). NOT HTTP/SSE as primary.
5. **Discovery: event-driven incremental** on every case ingest, 30-second debounce, 5-min periodic sweep. NOT batch.
6. **Two-tier artifact model:** campaign packs (instance knowledge, scale with campaigns) vs core skills (campaign-agnostic rules, barely move). This is the scaling answer.
7. **Frontend: separate Vite+React app** at `frontend/enterprise/`. Do NOT extend `frontend/transafe/`.
8. **Animation rule: every animation is driven by a real `ns_event` over WebSocket. Never a CSS timer.**
9. **Orchestration is deterministic by design.** Reasoning sits only where the action space is genuinely open: the phishing worker's planner and the Liaison Agent.
10. **Nothing autonomous reaches a customer.** Discovery is autonomous; action is human-approved.

## Build plan (ordered blocks)

Implementation follows the build plan from `01_upgrade_plan.md` §17. Each block produces a demoable system. **Do not skip ahead.** Work through the blocks in order — there are no time constraints. Take as long as needed to get each block right, with full test coverage, before moving on.

| Block | Deliverable | Modules to implement |
|---|---|---|
| **B0** | DB migration, `ns_events` emitter, `/enterprise/ws/events`, console shell + live feed | `events.py`, `v2_enterprise.sql`, WebSocket endpoint, `frontend/enterprise/` shell |
| **B1** | MO extractor, entity resolver, `OBSERVED` state, seed corpus | `mo_extractor.py`, `entity_resolver.py`, seed scripts |
| **B2** | Linkage, clustering, discovery trigger, GraphStore, `/enterprise/graph` | `linkage.py`, `clustering.py`, `discovery.py`, `graph_store.py` |
| **B3** | Graph screen, validation console, approve/reject | Frontend screens C+D, API endpoints |
| **B4** | Compiler (pack tier), registry, diff view, workers load from registry | `compiler.py`, `registry.py`, worker integration |
| **B4b** | Generaliser (core tier), core/pack tabs on Screen E | `generaliser.py`, Screen E tabs |
| **B5** | Propagation, consumption receipts (3 workers) | `propagation.py`, worker acknowledgment |
| **B6** | MCP server, Liaison Agent, role redaction, CodeBuddy config | `mcp/server.py`, `liaison_agent.py`, `mcp/redaction.py` |
| **B7** | Evaluation harness, eval screen, effectiveness write-back | `evaluation.py`, `metrics.py`, `corpus.py`, Screen F |
| **B7b** | Adaptation loop: miss → generaliser → approve → re-run | Integration of eval + generaliser |
| **B8** | Overview polish: nervous-system animation, metric bars | Frontend Screen A polish |
| **B9** | Record REPLAY from LIVE run, scenario runner, reset | Demo scripts, replay recording |
| **B10** | Final pass: fix any remaining bugs, verify end-to-end demo flow | Bug fixes only |

**Critical path: B0 → B1 → B2 → B4.** Everything else is enhancement.
**Never cut: B2 (discovery) and B4 (artifact + diff).** Those two *are* the product.

## How to spin up sub-agents — DO THIS FIRST

You have access to the `team_create` and `Task` tools. **Use them.** Do not try to implement everything in a single thread. Create a team, then spawn named team members that work in parallel.

### Step 1: Create the team

Call `team_create` with:
- `team_name`: `"transafe-v2-impl"`
- `description`: `"TranSafe v2 Enterprise Upgrade implementation — 5 parallel teams building backend core, artifacts, MCP, frontend, and evaluation"`

### Step 2: Spawn team members

Spawn each team member using the `Task` tool with `team_name="transafe-v2-impl"` and `mode="acceptEdits"` (so they can write code without blocking on approvals). Spawn **Team 1 and Team 4 first** (they are independent). Spawn Teams 2, 3, 5 after their dependencies complete.

Here are the exact prompts to use for each team member:

---

#### Team 1: `backend-core` (spawn immediately)

```
You are implementing the backend core of TranSafe v2's enterprise layer (blocks B0 → B1 → B2).

FIRST: Read these docs in full before writing any code:
- doc/transafe_v2/01_upgrade_plan.md (master plan — focus on §3, §4, §5, §6, §12, §13, §16)
- doc/transafe_v2/02_discovery_design.md (full function signatures + unit test specs)

THEN implement these modules in order under backend/src/enterprise/:

1. backend/migrations/v2_enterprise.sql — all new tables (ns_events, entities, case_entity_links, case_links, case_mo, campaigns, campaign_cases, artifacts, artifact_consumption, mcp_access_log, eval_runs). See §12 of the master plan and §7 of the discovery doc for full DDL.

2. enterprise/events.py — ns_events emitter. Writes to ns_events table AND broadcasts over WebSocket. See 02_discovery_design.md for the emit_event() signature.

3. enterprise/mo_extractor.py — extracts MO fingerprint from a case transcript using DeepSeek LLM, with structural regex fallback. See 02_discovery_design.md §3.

4. enterprise/entity_resolver.py — normalises and resolves entities (PHONE, ACCOUNT, URL, DOMAIN, NAME) across cases. See 02_discovery_design.md §4.

5. enterprise/graph_store.py — GraphStore protocol + PostgresGraphStore implementation. See 02_discovery_design.md §8.

6. enterprise/linkage.py — 4-signal case-pair scoring (entity overlap, MO similarity, temporal proximity, geographic proximity) with noisy-OR fusion. See 02_discovery_design.md §5.

7. enterprise/clustering.py — connected-component clustering with promotion gates (≥3 cases, ≥1 edge at 0.80, distinct customers, 14-day window) and novelty check (cosine 0.90 → merge). See 02_discovery_design.md §6.

8. enterprise/discovery.py — orchestrator: OBSERVED state on single cases, debounce (30s), trigger linkage+clustering on ingest, 5-min periodic sweep. See 02_discovery_design.md §9.

ALSO implement the API endpoints:
- backend/src/api/enterprise/ — FastAPI router with: GET /enterprise/overview, GET /enterprise/api/cases, GET /enterprise/api/cases/:id, GET /enterprise/api/graph, POST /enterprise/api/discovery/run
- backend/src/api/enterprise_ws.py — WebSocket endpoint at /enterprise/ws/events that streams ns_events

TECH PATTERNS:
- LLM: use langchain-openai ChatOpenAI with base_url="https://api.deepseek.com/v1", model="deepseek-chat", api_key from DEEPSEEK_API_KEY env var
- Embeddings: DashScope text-embedding-v3 (1024-dim) via httpx POST to https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
- Supabase: reuse get_supabase_client() from backend/src/db/vector_store.py
- JSON parsing: reuse extract_json_object() from backend/src/agents/llm.py

TESTING:
- Write unit tests for EVERY module in backend/tests/unit/
- Mock all external calls (LLM, Supabase, embeddings) with unittest.mock
- Follow def test_*() naming
- The companion doc 02_discovery_design.md has a "Testing" section per module with exact test cases — implement them
- Run: cd backend && uv run pytest tests/unit/test_mo_extractor.py test_entity_resolver.py test_linkage.py test_clustering.py test_discovery.py test_graph_store.py test_events.py -v
- Run: cd backend && uv run ruff check src/enterprise/ tests/unit/

Send a message to "main" when B2 is complete so Teams 2, 3, 5 can start.
```

---

#### Team 4: `frontend` (spawn immediately, parallel with Team 1)

```
You are implementing the TranSafe v2 Enterprise Console frontend (blocks B0 shell → B3 → B8).

FIRST: Read these docs in full before writing any code:
- doc/transafe_v2/01_upgrade_plan.md (focus on §14, §15)
- doc/transafe_v2/05_frontend_spec.md (full component specs + Vitest tests)

THEN:

1. Scaffold frontend/enterprise/ as a new Vite + React + TypeScript project:
   - Dependencies: react, react-dom, react-router-dom, zustand, framer-motion, lucide-react, recharts
   - Dev deps: vite, @vitejs/plugin-react, typescript, vitest, @testing-library/react, @testing-library/jest-dom, eslint, @typescript-eslint/eslint-plugin
   - vite.config.ts with proxy to backend on :8000

2. Implement the WebSocket event store (src/stores/useEventStore.ts):
   - Connects to /enterprise/ws/events
   - Stores all ns_events in a ring buffer (max 500)
   - Exposes filtered selectors by layer, severity, event_type
   - Supports REPLAY mode (reads from /enterprise/api/demo/replay and injects events at recorded timestamps) and LIVE mode (real WebSocket)

3. Implement 7 screens (see 05_frontend_spec.md for full specs):
   - Screen A: Overview — nervous-system visualization, metric bars, live event ticker
   - Screen B: Case Detail — MO fingerprint, entities, linkage trace, worker findings
   - Screen C: Scam Graph — force-directed graph of cases + campaigns, zoom/pan
   - Screen D: Validation Console — campaign candidates, approve/reject buttons, evidence panel
   - Screen E: Artifact Registry — two-tier view (core/pack tabs), version history, diff viewer, rollback button
   - Screen F: Evaluation — before/after bars, per-metric cards, adaptation timeline
   - Screen G: MCP Log — query history, role selector showing redaction differences

4. CRITICAL RULE: Every animation must be driven by a real ns_event from the WebSocket. Never use CSS timers, setInterval, or setTimeout for visual effects.

5. Implement shared components:
   - NerveMap (animated node graph for Screen A)
   - EventTicker (scrolling event feed)
   - StatusBadge (risk tier, campaign status, artifact tier)
   - DiffViewer (line-by-line diff for artifact versions)

TESTING:
- Write Vitest tests for every component
- Mock the WebSocket store in tests
- See 05_frontend_spec.md for test specs per component
- Run: cd frontend/enterprise && npm test
- Run: cd frontend/enterprise && npm run lint

You can start the B0 shell (empty screens with routing + WebSocket connection) immediately in parallel with Team 1's backend work. Fill in real data as backend endpoints become available.

Send a message to "main" when the B0 shell is scaffolded, and again when each screen is complete.
```

---

#### Team 2: `backend-artifacts` (spawn after Team 1 signals B2 complete)

```
You are implementing TranSafe v2's artifact compiler, generaliser, registry, and propagation (blocks B4 → B4b → B5).

FIRST: Read these docs in full before writing any code:
- doc/transafe_v2/01_upgrade_plan.md (focus on §7, §8, §12, §13)
- doc/transafe_v2/03_artifact_registry.md (full function signatures + unit test specs)

PREREQUISITE: Team 1 (backend-core) must have completed B2 — you need campaigns, graph_store, entity_resolver, and the v2_enterprise.sql migration to exist.

THEN implement these modules under backend/src/enterprise/:

1. enterprise/compiler.py — takes an approved campaign, compiles 5 artifact types (detection_rules.md, advisory_template.md, risk_score_overrides.json, narrative.md, entity_watchlist.json) using DeepSeek. See 03_artifact_registry.md §3.

2. enterprise/registry.py — append-only versioned store for both tiers (core + pack). Functions: publish(), get(), list(), diff(), rollback(), write_effectiveness(). See 03_artifact_registry.md §5.

3. enterprise/generaliser.py — examines ≥2 approved campaigns, finds cross-campaign invariants, emits a core-skill patch. Must pass agnosticism validator (C1: no campaign-specific entities, C2: no campaign-specific temporal refs). May emit empty. See 03_artifact_registry.md §4.

4. enterprise/propagation.py — on artifact publish, emits propagation_event per subscribed agent. Agents acknowledge by writing artifact_consumption receipts. See 03_artifact_registry.md §6.

ALSO implement API endpoints:
- GET /enterprise/api/artifacts (filter by tier, name)
- GET /enterprise/api/artifacts/:name/:version (with diff to previous)
- POST /enterprise/api/artifacts/:name/rollback
- GET /enterprise/api/campaigns
- POST /enterprise/api/campaigns/:id/approve

TECH PATTERNS:
- LLM: DeepSeek via langchain-openai (same as Team 1)
- Supabase: reuse get_supabase_client()
- JSON parsing: reuse extract_json_object()

TESTING:
- Write unit tests in backend/tests/unit/ for compiler, generaliser, registry, propagation
- Mock LLM and Supabase
- See 03_artifact_registry.md "Testing" section per module
- Run: cd backend && uv run pytest tests/unit/test_compiler.py test_generaliser.py test_registry.py test_propagation.py -v
- Run: cd backend && uv run ruff check src/enterprise/ tests/unit/

Send a message to "main" when B5 is complete so Team 3 (MCP) can start.
```

---

#### Team 3: `mcp-liaison` (spawn after Team 2 signals B5 complete)

```
You are implementing TranSafe v2's MCP gateway, Liaison Agent, and role-based redaction (block B6).

FIRST: Read these docs in full before writing any code:
- doc/transafe_v2/01_upgrade_plan.md (focus on §9, §10)
- doc/transafe_v2/04_mcp_gateway.md (full tool schemas + unit test specs)

PREREQUISITE: Teams 1 + 2 must have completed — you need campaigns, cases, registry, artifacts to exist.

THEN implement these modules:

1. backend/mcp/server.py — MCP server with stdio transport. Exposes 6 tools: query_campaign, query_case, query_artifact, query_stats, query_mcp_log, ask_transafe. Rate limit (60/min). Audit log to mcp_access_log. See 04_mcp_gateway.md §3.

2. backend/mcp/redaction.py — role-based recursive field redaction. 6 roles: fraud_ops, compliance, customer_service, partner_bank, auditor, public. Redaction happens BEFORE the Liaison Agent sees the data. See 04_mcp_gateway.md §4.

3. backend/src/enterprise/liaison_agent.py — 4-iteration retrieval loop: (1) classify intent, (2) plan retrieval steps, (3) execute tool calls with redaction, (4) synthesise answer with citations. Uses DeepSeek. Has deterministic fallback. See 04_mcp_gateway.md §5.

4. CodeBuddy MCP config file at backend/mcp/codebuddy_config.json — stdio connection config for CodeBuddy to connect to the MCP server. See 04_mcp_gateway.md §6.

ALSO implement API endpoint:
- GET /enterprise/api/mcp/log — recent MCP access log entries

TECH PATTERNS:
- Use the `mcp` Python package (pip install mcp) for the MCP server framework
- LLM: DeepSeek via langchain-openai
- Redaction is recursive: walks dicts/lists, replaces field values with "[REDACTED]" per role rules

TESTING:
- Write unit tests in backend/tests/unit/ for mcp_server, redaction, liaison_agent
- Mock LLM, Supabase, and the MCP transport
- See 04_mcp_gateway.md "Testing" section per module
- Run: cd backend && uv run pytest tests/unit/test_mcp_server.py test_redaction.py test_liaison_agent.py -v
- Run: cd backend && uv run ruff check mcp/ src/enterprise/liaison_agent.py tests/unit/

Send a message to "main" when B6 is complete.
```

---

#### Team 5: `eval-demo` (spawn after Team 2 signals B5 complete, parallel with Team 3)

```
You are implementing TranSafe v2's evaluation harness, adaptation loop, seed corpus, and demo controller (blocks B7 → B7b → B9).

FIRST: Read these docs in full before writing any code:
- doc/transafe_v2/01_upgrade_plan.md (focus on §11, §15)
- doc/transafe_v2/07_evaluation.md (full function signatures + unit test specs)
- doc/transafe_v2/06_demo_runbook.md (seed corpus specs, replay sequence, demo controller)

PREREQUISITE: Teams 1 + 2 must have completed — you need the full pipeline (discovery + artifacts + registry) to evaluate.

THEN implement these modules:

1. backend/src/enterprise/evaluation.py — runs the corpus through the pipeline twice (before artifact, after artifact), collects metrics, writes eval_runs row. See 07_evaluation.md §3.

2. backend/src/enterprise/metrics.py — computes: detection_rate, false_positive_rate, mean_time_to_detect, adaptation_delta, coverage. See 07_evaluation.md §4.

3. backend/src/enterprise/corpus.py — generates/loads the 40-case evaluation corpus (20 base scam variants, 10 red-team edge cases, 10 legitimate controls). See 07_evaluation.md §5.

4. backend/seeds/ — seed corpus:
   - transcripts/ — 10 synthetic fraud call transcripts (6 SCAM-027 wave + 4 background noise)
   - ground_truth/expected_results.json — expected MO, entities, campaign assignments
   - ns_events/replay_sequence.json — pre-recorded ns_events for REPLAY mode (the 5-act demo)
   - eval/ — 40-case evaluation corpus files
   All fictional. Malaysian scam scripts. See 06_demo_runbook.md for the 5-act structure.

5. backend/src/api/enterprise_demo.py — demo controller API:
   - POST /enterprise/api/demo/seed — load seed corpus
   - POST /enterprise/api/demo/replay/start — start REPLAY mode
   - POST /enterprise/api/demo/replay/stop — stop REPLAY
   - POST /enterprise/api/demo/reset — clear all v2 data, re-seed
   - POST /enterprise/api/eval/run — run evaluation
   - GET /enterprise/api/eval/latest — get latest before/after results

6. The adaptation loop (B7b): when evaluation finds a miss, feed the missed case to the generaliser, auto-approve if confidence > 0.8, re-run evaluation. See 07_evaluation.md §6.

TESTING:
- Write unit tests in backend/tests/unit/ for evaluation, metrics, corpus
- Mock the pipeline calls
- See 07_evaluation.md "Testing" section per module
- Run: cd backend && uv run pytest tests/unit/test_evaluation.py test_metrics.py test_corpus.py -v
- Run: cd backend && uv run ruff check src/enterprise/ tests/unit/

Send a message to "main" when B7b is complete.
```

---

### Step 3: Coordinate

After spawning team members, your job as the main agent is to:
1. **Monitor progress** — team members will send you messages when they complete blocks
2. **Spawn the next wave** — when Team 1 signals B2 done, spawn Teams 2 + 5; when Team 2 signals B5 done, spawn Team 3
3. **Resolve blockers** — if a team member reports a dependency that doesn't exist yet, coordinate with the team that should have built it
4. **Integration test** — once all teams complete their blocks, run the full test suite and verify the demo flow end-to-end
5. **Use `send_message`** to communicate with team members. Use `shutdown_request` when a team is done.

### Execution order

```
Phase 1:  Spawn Team 1 (backend-core) + Team 4 (frontend) in parallel
Phase 2:  When Team 1 signals B2 done → spawn Team 2 (backend-artifacts) + Team 5 (eval-demo)
Phase 3:  When Team 2 signals B5 done → spawn Team 3 (mcp-liaison)
Phase 4:  When all teams complete → integration testing
Phase 5:  Polish + final verification
```

There is no clock — take the time needed for full correctness and test coverage at each phase.

## How to read the design docs

Before writing any code, **read these files in order**:

| Doc | What it contains | When to read |
|---|---|---|
| `doc/transafe_v2/01_upgrade_plan.md` | Master plan — 6 layers, architecture, data model, API surface, build plan | Before starting anything |
| `doc/transafe_v2/02_discovery_design.md` | Full function signatures for mo_extractor, entity_resolver, linkage, clustering, discovery, graph_store + unit tests | Before implementing B1-B2 |
| `doc/transafe_v2/03_artifact_registry.md` | Two-tier model, compiler, generaliser, registry, propagation + unit tests | Before implementing B4-B5 |
| `doc/transafe_v2/04_mcp_gateway.md` | MCP server, Liaison Agent, role redaction, CodeBuddy config + unit tests | Before implementing B6 |
| `doc/transafe_v2/05_frontend_spec.md` | 7 screens, visual language, components, WebSocket, REPLAY/LIVE + Vitest tests | Before implementing frontend |
| `doc/transafe_v2/06_demo_runbook.md` | 5-act demo, seed corpus, replay recording, demo controller | Before implementing B9 |
| `doc/transafe_v2/07_evaluation.md` | Eval corpus, metrics, harness, adaptation loop + unit tests | Before implementing B7 |

Each companion doc contains:
- **Full function signatures** with type hints
- **SQL DDL** for new tables
- **API endpoint definitions**
- **React component specs** (frontend doc)
- **Per-module unit test sections** with test cases and code

## Testing requirements

**Every module must have unit tests. No exceptions.**

- **Backend:** pytest + pytest-asyncio + ruff
- **Frontend:** Vitest + React Testing Library + ESLint
- **All tests mock external dependencies** (LLM, Supabase, embeddings) — no real API keys needed
- **Follow `def test_*()` naming** — pytest auto-discovers
- **Run tests after each block:**

```bash
# Backend tests
cd backend && uv run pytest tests/unit/ -v

# Backend lint
cd backend && uv run ruff check src/enterprise/ mcp/ tests/unit/

# Frontend tests
cd frontend/enterprise && npm test

# Frontend lint
cd frontend/enterprise && npm run lint
```

The `pyproject.toml` already has pytest, pytest-asyncio, and ruff as dev dependencies. Add this ruff config:

```toml
[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

## Key technical patterns to follow

### LLM invocation (DeepSeek via langchain-openai)

```python
from langchain_openai import ChatOpenAI
import os

def get_deepseek_llm(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
        temperature=temperature,
    )
```

Reuse `extract_json_object()` from `backend/src/agents/llm.py` for parsing LLM JSON output.

### Embeddings (DashScope text-embedding-v3)

```python
import os
import httpx

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY")
DASHSCOPE_EMBED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"

def embed_text(text: str) -> list[float]:
    resp = httpx.post(
        DASHSCOPE_EMBED_URL,
        headers={"Authorization": f"Bearer {DASHSCOPE_API_KEY}"},
        json={"model": "text-embedding-v3", "input": text},
        timeout=30,
    )
    return resp.json()["data"][0]["embedding"]  # 1024-dim
```

### Supabase access

Reuse `get_supabase_client()` from `backend/src/db/vector_store.py`.

### Event emission

```python
from enterprise.events import emit_event

await emit_event(
    layer="discovery",
    event_type="campaign_proposed",
    payload={"campaign_id": "c1", "confidence": 0.87},
    severity="critical",
    run_id="demo-run-1",
)
```

### Role-based redaction

Redaction is **server-side, before synthesis**. The Liaison Agent never sees fields the caller is not entitled to.

```python
from mcp.redaction import redact_by_role

redacted = redact_by_role(raw_data, role="compliance")
# PII, transcripts, account numbers → "[REDACTED]"
```

## Database migration

New tables only — all v1 tables untouched. The full DDL is in `01_upgrade_plan.md` §12 and `02_discovery_design.md` §7.

Key tables:
- `ns_events` — the organisational nervous system event log
- `entities` — resolved entities (PHONE, ACCOUNT, URL, DOMAIN, NAME)
- `case_entity_links` — case ↔ entity links
- `case_links` — weighted case-case edges
- `case_mo` — MO fingerprints per case
- `campaigns` — campaign candidates and approved campaigns
- `campaign_cases` — campaign ↔ case membership
- `artifacts` — versioned, tiered (core/pack)
- `artifact_consumption` — consumption receipts
- `mcp_access_log` — MCP call audit log
- `eval_runs` — evaluation run results

## API surface

All new endpoints under `/enterprise`. v1 endpoints untouched.

Key endpoints:
- `GET /enterprise/overview` — dashboard stats
- `GET /enterprise/api/cases` — list cases
- `GET /enterprise/api/cases/:id` — case detail with MO + entities + trace
- `GET /enterprise/api/graph` — full graph data
- `GET /enterprise/api/campaigns` — list campaigns
- `POST /enterprise/api/campaigns/:id/approve` — approve campaign
- `GET /enterprise/api/artifacts` — list artifacts (filter by tier)
- `GET /enterprise/api/artifacts/:name/:version` — artifact with diff
- `POST /enterprise/api/artifacts/:name/rollback` — rollback
- `POST /enterprise/api/discovery/run` — force discovery sweep
- `POST /enterprise/api/eval/run` — run evaluation
- `GET /enterprise/api/eval/latest` — before/after comparison
- `GET /enterprise/api/mcp/log` — MCP access log
- `WS /enterprise/ws/events` — live ns_events stream

## Seed corpus

Located at `backend/seeds/`:
- `transcripts/` — 10 synthetic fraud transcripts (6 SCAM-027 wave, 4 noise)
- `ground_truth/` — expected MO, entities, campaign for evaluation
- `ns_events/replay_sequence.json` — pre-recorded events for REPLAY mode
- `eval/` — 40-case evaluation corpus (20 base, 10 red-team, 10 noise)

All fictional victims, fictional accounts, fictional domains.

## What success looks like

After implementation, you should be able to:

1. **Run the backend:** `cd backend && uv run uvicorn main:app --reload --port 8000` (the app is `backend/main.py` — not `src.api.main`)
2. **Run the frontend:** `cd frontend/enterprise && npm run dev -- --port 5174`
3. **Run all tests:** `cd backend && uv run pytest tests/unit/ -v` → all green
4. **Run the demo:**
   - Seed the corpus → start REPLAY mode → watch 5 acts play out
   - Switch to LIVE mode → type a scam message → watch real-time detection
   - See CodeBuddy call the MCP server and get a cited, redacted answer
5. **Run evaluation:** `POST /enterprise/api/eval/run` → see before/after bars on Screen F

## Non-negotiable rules

1. **Do not rewrite v1.** Wrap it. Zero changes to `backend/src/agents/` worker code, `frontend/transafe/`, or v1 API endpoints.
2. **Every module has unit tests.** No module is "done" until its tests pass.
3. **Every animation is event-driven.** No CSS timers on the frontend.
4. **Orchestration is deterministic.** Only the Liaison Agent and phishing planner use LLM-based reasoning, and both are gated, bounded, and have fallbacks.
5. **Nothing autonomous reaches a customer.** Campaigns require human approval before compilation.
6. **Redaction is server-side.** The Liaison Agent never sees fields the caller is not entitled to.
7. **Follow the build order.** B0 → B1 → B2 → B4 is the critical path. Do not jump ahead.
8. **Read the docs before coding.** Each companion doc has full function signatures — implement them as specified.

---

## Quick-start checklist

```
□ Read doc/transafe_v2/01_upgrade_plan.md (master plan)
□ Read the relevant companion doc(s) for your assigned block
□ Check backend/pyproject.toml for existing deps
□ Create team via team_create tool
□ Spawn Team 1 (backend-core) + Team 4 (frontend) via Task tool with team_name
□ Monitor progress via send_message — wait for Team 1 to signal B2 done
□ Spawn Team 2 (backend-artifacts) + Team 5 (eval-demo)
□ Wait for Team 2 to signal B5 done → spawn Team 3 (mcp-liaison)
□ Each team writes unit tests for their modules
□ Run: cd backend && uv run pytest tests/unit/ -v
□ Run: cd backend && uv run ruff check src/enterprise/ mcp/ tests/unit/
□ Run: cd frontend/enterprise && npm test
□ Run: cd frontend/enterprise && npm run lint
□ Integration test the full demo flow end-to-end
□ Shutdown team members when their work is complete
```

**Start by reading `doc/transafe_v2/01_upgrade_plan.md` in full. Then create your team and spawn sub-agents per the instructions in "How to spin up sub-agents". Do not write code yourself — delegate to team members and coordinate.**
