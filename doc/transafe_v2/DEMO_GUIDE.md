# TranSafe v2 — Demo Guide

> Step-by-step instructions to run the full TranSafe v2 Enterprise Console demo.

---

## Prerequisites

### 1. Environment variables

Ensure `backend/.env` contains at minimum:

```env
DEEPSEEK_API_KEY=sk-...           # Required for LLM features (MO extraction, artifact compilation)
DEEPSEEK_MODEL_PRIMARY=deepseek-chat
SUPABASE_URL=https://...           # Required for all database operations
SUPABASE_SERVICE_KEY=eyJ...        # Required for all database operations
```

Optional (not needed for the demo):

```env
DASHSCOPE_API_KEY=sk-...          # For text-embedding-v3 (narrative linkage signal + novelty check)
```

**Without DashScope:** The system falls back to a deterministic local embedding vector. The demo still works end-to-end — the SCAM-027 cases share a mule account, overlapping entities, and similar MO structure, so the other 3 linkage signals (entity overlap, temporal proximity, geographic proximity) are strong enough to cluster them. DashScope would only make the narrative similarity signal more precise.

To verify your `.env`:

```bash
cd backend && grep -E "DEEPSEEK_API_KEY|SUPABASE_URL|SUPABASE_SERVICE_KEY" .env
```

### 2. Dependencies installed

```bash
# Backend
cd backend && uv sync

# Frontend
cd frontend/enterprise && npm install
```

### 3. Database migration

The v2 migration (`backend/migrations/v2_enterprise.sql`) creates 13 new tables in your Supabase Postgres. **This has already been applied** — all tables exist:

- `ns_events`, `entities`, `case_entity_links`, `case_links`, `case_mo`
- `campaigns`, `campaign_cases`, `artifacts`, `artifact_consumption`
- `mcp_access_log`, `eval_runs`, `case_discovery_state`, `eval_results`

You can verify at any time:

```bash
cd backend && uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from src.db.vector_store import get_supabase_client
c = get_supabase_client()
r = c.table('ns_events').select('id').limit(1).execute()
print('ns_events:', 'OK' if r.data is not None else 'MISSING')
r = c.table('campaigns').select('id').limit(1).execute()
print('campaigns:', 'OK' if r.data is not None else 'MISSING')
"
```

If you ever need to re-apply (e.g., fresh Supabase instance), paste the contents of `backend/migrations/v2_enterprise.sql` into the Supabase SQL Editor and run it. The migration is idempotent.

---

## Step 1 — Start the backend

```bash
cd backend && uv run uvicorn main:app --reload --port 8000
```

You should see:

```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete.
```

Verify the API is alive:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "healthy", "version": "1.0.0", ...}
```

---

## Step 2 — Start the frontend

In a new terminal:

```bash
cd frontend/enterprise && npm run dev
```

You should see:

```
  VITE v5.x  ready in xxx ms
  ➜  Local:   http://localhost:5174/
```

**Note:** The enterprise console runs on port **5174** (not 5173 — that's the v1 consumer app).

Open your browser to: **http://localhost:5174**

You should see the Overview screen with the nervous-system visualization, empty metric bars, and a live event ticker (may show heartbeat frames until data is seeded).

---

## Step 3 — Seed the demo corpus

Load the fictional SCAM-027 seed data (10 cases, entities, MO fingerprints):

```bash
curl -X POST http://localhost:8000/enterprise/demo/seed
```

Expected response:

```json
{
  "status": "ok",
  "counts": {
    "users": 10,
    "fraud_cases": 10,
    "call_transcripts": 200,
    "case_mo": 10,
    "entities": 25,
    "case_entity_links": 40
  },
  "warnings": []
}
```

**If you see warnings:** Check that the migration was applied (Step 3 of Prerequisites). Warnings about "embedding" mean `DASHSCOPE_API_KEY` is missing — the system falls back to deterministic local vectors and the demo still works without it.

**After seeding, refresh the browser.** You should now see:
- Overview screen: metric bars populated, entity counts showing
- Cases screen: 10 cases listed with risk scores
- Graph screen: entities and their case links visible

---

## Step 4 — Run discovery (linkage + clustering)

Trigger the discovery pipeline to link cases, cluster them, and propose campaigns:

```bash
curl -X POST http://localhost:8000/enterprise/discovery/run
```

This runs the full pipeline:
1. **MO extraction** — extracts/refreshes MO fingerprints for each case
2. **Entity resolution** — normalises and links shared entities (phones, accounts, names)
3. **Linkage** — scores all case pairs (4-signal noisy-OR fusion)
4. **Clustering** — groups linked cases, applies promotion gates (≥3 cases, ≥1 edge ≥0.80, distinct customers, 14-day window)
5. **Campaign proposal** — promotes qualifying clusters as campaign candidates

**Expected outcome:** The SCAM-027 wave (6 cases sharing a mule account and authority-claim MO) should be discovered as a campaign candidate. The 4 noise cases (phishing, investment, romance) should remain unlinked.

After running, check the results:

```bash
# See the overview
curl http://localhost:8000/enterprise/overview | python3 -m json.tool

# See the scam graph
curl http://localhost:8000/enterprise/graph | python3 -m json.tool

# See campaign candidates
curl http://localhost:8000/enterprise/campaigns | python3 -m json.tool
```

**In the browser:**
- **Graph screen** (`/graph`): Nodes for cases and entities, edges showing linkage. The SCAM-027 cluster should be visibly connected.
- **Validation screen** (`/validation`): Campaign candidates awaiting approval with evidence.

---

## Step 5 — Approve a campaign

Find the SCAM-027 campaign candidate and approve it:

```bash
# List campaigns to find the ID
curl http://localhost:8000/enterprise/campaigns | python3 -m json.tool
```

Look for a campaign with `status: "candidate"` and approve it:

```bash
# Replace <CAMPAIGN_ID> with the actual ID from the list above
curl -X POST http://localhost:8000/enterprise/campaigns/<CAMPAIGN_ID>/approve \
  -H "Content-Type: application/json" \
  -d '{"note": "Approved in demo run"}'
```

**What happens on approval:**
1. Campaign status changes to `approved`
2. The **compiler** generates 5 artifact types: `detection_rules.md`, `advisory_template.md`, `risk_score_overrides.json`, `narrative.md`, `entity_watchlist.json`
3. The **generaliser** examines the campaign for cross-campaign invariants (may emit a core-tier patch)
4. The **registry** stores the artifacts as a versioned set
5. **Propagation** pushes the artifacts to subscribed workers (phone, phishing, financial agents)
6. `ns_events` are emitted at every step — watch the live event ticker in the browser

---

## Step 6 — View artifacts

See the compiled artifacts:

```bash
# List all artifacts
curl http://localhost:8000/enterprise/artifacts | python3 -m json.tool

# Get a specific artifact (replace name and version)
curl http://localhost:8000/enterprise/artifacts/detection_rules/1 | python3 -m json.tool
```

**In the browser:**
- **Registry screen** (`/registry`): Two-tier view (core/pack tabs). Click any artifact to see its content, version history, and diff to previous version.

---

## Step 7 — Run the evaluation

Run the evaluation harness to measure before/after metrics:

```bash
curl -X POST http://localhost:8000/enterprise/eval/run \
  -H "Content-Type: application/json" \
  -d '{}'
```

This runs the 40-case evaluation corpus through the pipeline twice:
1. **Before** — without the campaign artifacts active
2. **After** — with the campaign artifacts active

```bash
# Get the latest evaluation results
curl http://localhost:8000/enterprise/eval/latest | python3 -m json.tool
```

**Expected metrics:**
- **Detection rate** — should improve after artifacts (from ~30% to ~80%+)
- **False positive rate** — should stay low (<15%)
- **Adaptation delta** — positive number showing improvement

**In the browser:**
- **Eval screen** (`/eval`): Before/after bar charts, per-metric cards, adaptation timeline.

---

## Step 8 — Run the adaptation loop (B7b)

If evaluation found a miss (a case the artifacts didn't catch), run the adaptation loop:

```bash
curl -X POST http://localhost:8000/enterprise/eval/adaptation
```

This:
1. Finds the missed case
2. Feeds it to the **generaliser** to create a core-tier patch
3. Auto-approves if confidence > 0.8
4. Re-runs evaluation to measure the improvement

---

## Step 9 — REPLAY mode (5-act demo)

Instead of the manual steps above, you can run the pre-recorded 5-act demo sequence:

### Act 1-4: Replay the recorded sequence

```bash
# Start replay at 2x speed (to move faster; use 1.0 for real-time)
curl -X POST http://localhost:8000/enterprise/demo/replay/start \
  -H "Content-Type: application/json" \
  -d '{"speed": 2.0}'
```

**In the browser**, the console automatically switches to REPLAY mode:
- **Act 1 (~90s):** Victim phone call ingested, MO extracted, entities linked — visible on Overview + Case Detail screens
- **Act 2 (~60s):** Campaign discovery — cases cluster, cluster tightens, candidate proposed — visible on Overview
- **Act 4 (~60s):** Artifact compiled, versioned, diffed, propagated — visible on Registry screen

Check replay status:

```bash
curl http://localhost:8000/enterprise/demo/status | python3 -m json.tool
```

Stop replay early if needed:

```bash
curl -X POST http://localhost:8000/enterprise/demo/replay/stop
```

---

## Step 10 — Connect CodeBuddy as the Compliance department (MCP)

This is Act 5 of the demo: CodeBuddy connects to TranSafe's MCP server as a `compliance` role, queries fraud intelligence, and the Liaison Agent answers with role-based redaction applied.

### What the compliance role can see

| Can see | Cannot see |
|---------|------------|
| Campaign details, MO fingerprints, indicators, artifacts, compliance briefs, case IDs, aggregate stats | Transcripts, victim names, phone numbers, account numbers, customer PII, raw case evidence |

Redaction is **server-side and structural** — it runs on the payload before the Liaison Agent sees it. CodeBuddy literally cannot read fields it's not entitled to. This is not a prompt instruction; it cannot be prompt-injected away.

### Step 10a: Ensure the backend is running

The MCP server uses the same Supabase connection and env vars as the backend. Make sure the backend is already running (Step 1) so the database is accessible.

### Step 10b: Configure CodeBuddy's MCP settings

CodeBuddy stores MCP server config in `~/.codebuddy/mcp.json`. Edit it:

```bash
nano ~/.codebuddy/mcp.json
```

Replace the contents with:

```json
{
  "mcpServers": {
    "transafe": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp.server"],
      "cwd": "/Users/Admin/Documents/GitHub/Transafe/backend",
      "env": {
        "TRANSAFE_CALLER": "codebuddy",
        "TRANSAFE_ROLE": "compliance",
        "TRANSAFE_LOG_LEVEL": "INFO"
      },
      "transport": "stdio"
    }
  }
}
```

Key settings:
- **`TRANSAFE_ROLE: "compliance"`** — this is the entitlement ceiling. CodeBuddy can request a narrower role per-call, but never a broader one. Launching with `compliance` and asking for `fraud_ops` gets you `compliance`.
- **`cwd`** — must point to your backend directory (where `uv` can find the project).
- **`TRANSAFE_CALLER: "codebuddy"`** — stamps every audit log entry so you can trace who called what.

Save and close. **Restart CodeBuddy** (or reload the window) so it picks up the new MCP config.

### Step 10c: Verify the connection

After CodeBuddy restarts, open a new CodeBuddy chat and type:

```
List all active TranSafe campaigns
```

CodeBuddy should call the `list_active_campaigns` MCP tool. The MCP server will:
1. Check the rate limit (60/min)
2. Verify the `compliance` role is entitled to the `campaign` resource category
3. Fetch campaign data from Supabase
4. Run `redact_by_role()` on the payload — redacting transcript text, PII, phone numbers, account numbers
5. Return the redacted result to CodeBuddy
6. Write an audit entry to `mcp_access_log`
7. Emit an `exposure/mcp_call` ns_event (visible live on console Screen G)

### Step 10d: Try these queries as compliance

Open a CodeBuddy chat and try these prompts:

**1. Ask about a campaign:**
```
Tell me about TranSafe campaign SCAM-027. What is the MO pattern and what indicators should I look for?
```

**2. Ask about an artifact:**
```
Show me the detection rules artifact for the latest SCAM-027 campaign.
```

**3. Ask a natural-language question (Liaison Agent):**
```
Ask TranSafe: what compliance briefs exist for authority-claim scams, and which cases are linked?
```
This triggers `ask_transafe` — the 4-iteration retrieval loop:
1. Classify intent (what is the caller asking?)
2. Plan retrieval steps (which tools to call?)
3. Execute tool calls with redaction applied before the LLM sees the data
4. Synthesize an answer with citations

**4. Check statistics:**
```
What are TranSafe's current stats? How many campaigns, cases, and artifacts?
```

### Step 10e: Compare roles (optional)

To see how redaction changes by role, edit `~/.codebuddy/mcp.json` and change `TRANSAFE_ROLE` to a different role, restart CodeBuddy, and ask the same questions:

| Role | What they see |
|------|---------------|
| `fraud_ops` | Everything — no restrictions |
| `compliance` | Campaigns, MO, indicators, artifacts, compliance briefs, case IDs. No transcripts/PII. |
| `customer_service` | Campaigns, CS advisories, indicators, artifacts. No compliance briefs, no case data. |
| `auditor` | Campaigns, case IDs, MO, compliance briefs, CS advisories, artifacts. No PII. |
| `analyst` | Campaigns, case IDs, MO, indicators, artifacts. No customer data. |
| `partner_bank` | Indicators, MO, aggregate stats only. No case IDs, no campaign identity. |
| `public` | Aggregate statistics only. Nothing else. |

For example, the same campaign viewed as `fraud_ops` shows victim names, phone numbers, and account numbers. The same query as `compliance` replaces all of those with `[REDACTED]`. As `partner_bank`, even the campaign code and case IDs disappear.

### Step 10f: Watch it live in the console

While CodeBuddy makes MCP calls, have the Enterprise Console open in your browser at `http://localhost:5174/mcp`:

- **MCP Log screen** shows every call in real time: the tool name, the caller (`codebuddy`), the role (`compliance`), the response status, and which fields were redacted
- The **Overview screen** event ticker shows `exposure/mcp_call` events as they happen
- Every call — success, denial, rate-limit rejection, error — is logged. An audit log that only records successes is useless for exactly the incident you'd want to investigate

### Step 10g: Check the audit log via API

```bash
curl http://localhost:8000/enterprise/mcp/log | python3 -m json.tool
```

Each entry shows:
- `caller` — who called (e.g., `codebuddy`)
- `role` — what role was used (e.g., `compliance`)
- `tool` — which MCP tool was called
- `params` — the call arguments (redacted per the viewer's own role)
- `result_summary` — what was returned
- `redacted_fields` — which categories were withheld
- `ts` — when it happened
- `status` — `ok`, `denied`, `rate_limited`, or `error`

---

## Step 11 — Reset and re-run

To clear all v2 state and start fresh:

```bash
curl -X POST http://localhost:8000/enterprise/demo/reset \
  -H "Content-Type: application/json" \
  -d '{"reseed": true}'
```

This:
1. Stops any running replay
2. Deletes all rows from v2 tables (ns_events, entities, campaigns, artifacts, etc.)
3. Re-seeds the demo corpus
4. v1 tables (users, fraud_cases, call_transcripts) are **never touched** — the purge list is hardcoded and checked against v1 tables at import time

---

## Full demo flow (quick reference)

```bash
# ── Terminal 1: Backend ──────────────────────────────
cd backend && uv run uvicorn main:app --reload --port 8000

# ── Terminal 2: Frontend ─────────────────────────────
cd frontend/enterprise && npm run dev
# Open http://localhost:5174

# ── Terminal 3: Demo commands ────────────────────────
# 1. Seed data
curl -X POST http://localhost:8000/enterprise/demo/seed

# 2. Run discovery
curl -X POST http://localhost:8000/enterprise/discovery/run

# 3. Check campaigns
curl http://localhost:8000/enterprise/campaigns | python3 -m json.tool

# 4. Approve campaign (replace ID)
curl -X POST http://localhost:8000/enterprise/campaigns/<ID>/approve \
  -H "Content-Type: application/json" -d '{}'

# 5. View artifacts
curl http://localhost:8000/enterprise/artifacts | python3 -m json.tool

# 6. Run evaluation
curl -X POST http://localhost:8000/enterprise/eval/run \
  -H "Content-Type: application/json" -d '{}'
curl http://localhost:8000/enterprise/eval/latest | python3 -m json.tool

# 7. OR — just replay the 5-act demo
curl -X POST http://localhost:8000/enterprise/demo/replay/start \
  -H "Content-Type: application/json" -d '{"speed": 2.0}'

# 8. Reset when done
curl -X POST http://localhost:8000/enterprise/demo/reset \
  -H "Content-Type: application/json" -d '{"reseed": true}'

# 9. Connect CodeBuddy as compliance department
# Edit ~/.codebuddy/mcp.json and add the transafe MCP server (see Step 10)
# Restart CodeBuddy, then ask: "Tell me about TranSafe campaign SCAM-027"
```

---

## Browser screen reference

| Screen | URL Path | What to look for |
|--------|----------|------------------|
| **Overview** | `/` | Nervous-system animation (driven by real ns_events), metric bars, live event ticker |
| **Case Detail** | `/cases` or `/cases/:id` | MO fingerprint, entities, linkage trace, worker findings |
| **Scam Graph** | `/graph` | Force-directed graph of cases + entities + campaigns. Zoom/pan. |
| **Validation** | `/validation` | Campaign candidates with evidence. Approve/reject buttons. |
| **Artifact Registry** | `/registry` | Core/pack tabs, version history, diff viewer, rollback button |
| **Evaluation** | `/eval` | Before/after bars, per-metric cards, adaptation timeline |
| **MCP Log** | `/mcp` | Query history, role selector showing redaction differences |

---

## Troubleshooting

### "ns_events table: MISSING"

The migration hasn't been applied. See Prerequisites §3.

### Frontend shows blank screen / no WebSocket data

1. Check backend is running: `curl http://localhost:8000/health`
2. Check WebSocket proxy: open browser DevTools → Network → WS. You should see a connection to `/enterprise/ws/events`.
3. The Vite proxy config forwards `/enterprise` to `http://localhost:8000` with `ws: true`.

### "counts": 0 after seeding

The seed likely hit a migration issue. Check for warnings in the response:

```bash
curl -X POST http://localhost:8000/enterprise/demo/seed | python3 -m json.tool
```

Look at the `"warnings"` array — it will name the table and error.

### Discovery produces no campaigns

- Ensure you seeded first (`/enterprise/demo/seed`)
- The SCAM-027 wave needs ≥3 cases with shared entities and similar MO to promote a cluster
- Check linkage scores: `curl http://localhost:8000/enterprise/graph | python3 -m json.tool`

### DeepSeek API errors

- Verify `DEEPSEEK_API_KEY` is set: `echo $DEEPSEEK_API_KEY` (or check `.env`)
- The system has a structural regex fallback for MO extraction when the API key is dead, so core functionality works without it
- Embeddings use a deterministic local fallback when `DASHSCOPE_API_KEY` is missing — the demo runs fine without DashScope
- Artifact compilation will use fallback templates if DeepSeek is unreachable

### Port conflicts

- Backend: `PORT=8080 uv run uvicorn main:app --reload --port 8080`
- Frontend: Edit `frontend/enterprise/vite.config.ts` → `server.port`

---

## What each step demonstrates

| Step | Build Block | What it proves |
|------|-------------|----------------|
| Seed | B0, B1 | DB schema works, MO fingerprints + entities load |
| Discovery | B2 | Linkage, clustering, campaign detection — the core product |
| Approve | B4, B4b, B5 | Compiler produces artifacts, generaliser extracts core tier, propagation pushes to workers |
| Artifacts | B4 | Registry stores, versions, diffs artifacts |
| Evaluation | B7, B7b | Before/after metrics, adaptation loop closes the gap |
| Replay | B9 | 5-act recorded demo runs end-to-end |
| MCP | B6 | External agent queries TranSafe safely with role-based redaction |
| Reset | B9 | Clean reset for re-runs without touching v1 data |
