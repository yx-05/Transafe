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
# No --reload for a demo: a mid-run restart drops background tasks that are
# still compiling or propagating, which looks like the pipeline failing.
cd backend && uv run uvicorn main:app --host 127.0.0.1 --port 8000
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

Expected response (counts verified against the current seeder):

```json
{
  "status": "ok",
  "counts": {
    "users": 16,
    "fraud_cases": 16,
    "call_transcripts": 210,
    "case_mo": 16,
    "campaigns": 2,
    "campaign_cases": 6,
    "artifacts": 1,
    "entities": 25,
    "case_entity_links": 41
  },
  "warnings": []
}
```

The seed covers more than the wave: **10 wave/noise cases** (SCAM-027) plus **6 cases behind two already-approved campaigns**, SCAM-019 and SCAM-024, and the published `phone_agent_core` **v6** baseline.

That extra history is load-bearing, not decoration. `maybe_generalise` refuses to propose a core-tier rule unless **three** approved campaigns exist (the new one plus two others), because a pattern present in a single campaign is by definition specific to it. Seed only the wave and the generaliser always declines — so the campaign-agnostic rule, the strongest artifact the system produces, would never exist outside the recorded replay. You can verify the precondition held:

```bash
curl http://localhost:8000/enterprise/campaigns | python3 -m json.tool   # expect SCAM-019 + SCAM-024, both APPROVED
curl http://localhost:8000/enterprise/artifacts  | python3 -m json.tool   # expect phone_agent_core v6, tier=core
```

**If you see warnings:** Check that the migration was applied (Step 3 of Prerequisites). Warnings about "embedding" mean `DASHSCOPE_API_KEY` is missing — the system falls back to deterministic local vectors and the demo still works without it.

**After seeding, refresh the browser.** You should now see:
- Header: `Cases 16+`, `⚠ Unrecognised`, `Campaigns 2`, `Core v6` (the counts are live, not fixtures)
- Overview screen: metric bars populated, entity counts showing
- Cases screen: the seeded cases listed with risk scores
- Graph screen: entities and their case links visible
- Registry screen **CORE** tab: `phone_agent_core` at version **v6** — the pre-campaign baseline the generaliser will patch

---

## Step 4 — Run discovery (linkage + clustering)

Trigger the discovery pipeline to link cases, cluster them, and propose campaigns. **Run it twice** — the first sweep links the cases, the second promotes the cluster:

```bash
# Sweep 1 — normalises entities, scores case pairs, writes case_links
curl -X POST http://localhost:8000/enterprise/discovery/run

# Sweep 2 — the cluster is now dense enough to clear the promotion gates
curl -X POST http://localhost:8000/enterprise/discovery/run
```

**Why twice.** Discovery is event-driven and debounced at 30 s, and a single sweep after a fresh reset reliably produces `cases_linked` events without promoting a candidate. Two sweeps produce the candidate within seconds. This is the single most common way the demo stalls, because the pipeline *looks* like it ran (the command returns `{"status":"started"}` and links appear) while no campaign is ever proposed. The endpoint is asynchronous — it returns immediately and works in the background.

**Expected outcome:** the SCAM-027 wave (6 cases sharing a mule account and an authority-claim MO) is discovered as a campaign candidate with 6 cases, 6 distinct customers and confidence ≈ 0.96. The 4 noise cases stay unlinked. The campaign is numbered **SCAM-027** — the allocator continues from the history the seed laid down, not from the row count.

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
# Replace <CAMPAIGN_ID> with the actual ID from the list above.
# `generalise: true` is what runs the core-tier pass — leave it out and you get
# the campaign pack but no phone_agent_core v7, which is the strongest artifact.
curl -X POST http://localhost:8000/enterprise/campaigns/<CAMPAIGN_ID>/approve \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "fraud_ops", "generalise": true}'
```

> **Body fields.** `approved_by` names the human on the audit trail. `generalise` (default `true`) also runs the generaliser. A body of `{"note": "..."}` is accepted but ignored — both fields take their defaults, which happens to include generalisation, but nothing is recorded from `note`.

**What happens on approval:**
1. Campaign status changes to `APPROVED` and a `campaign_approved` event is emitted
2. The **compiler** generates five pack-tier artifacts — see the names in Step 6
3. The **generaliser** looks for a cross-campaign invariant; with three approved campaigns present it proposes a `phone_agent_core` patch (may legitimately emit nothing)
4. The **registry** stores each artifact as a new version
5. **Propagation** offers each artifact to its subscribed worker
6. Each worker that *reads* an artifact writes a **consumption receipt** — this is what proves the artifact was used rather than merely published
7. `ns_events` are emitted at every step — watch the live event ticker in the browser

Compilation runs as a background task, so the HTTP response returns `{"status": "approved", "compilation": "started"}` before the artifacts exist. Poll the artifacts endpoint (or watch the Registry screen) until `phone_agent_core v7` appears — it takes a few seconds and needs one DeepSeek call per pass.

---

## Step 6 — View artifacts

See the compiled artifacts:

```bash
# List all artifacts (one row per name, at its highest published version)
curl http://localhost:8000/enterprise/artifacts | python3 -m json.tool

# Filter by tier
curl "http://localhost:8000/enterprise/artifacts?tier=core" | python3 -m json.tool

# Get one artifact with its diff against the previous version
curl http://localhost:8000/enterprise/artifacts/phone_agent_core/7 | python3 -m json.tool
```

**The real artifact names.** `IMPLEMENTATION_PROMPT.md` describes the five pack outputs as `detection_rules.md`, `advisory_template.md`, `risk_score_overrides.json`, `narrative.md` and `entity_watchlist.json`. Those are *alias renderings* of the same five artifacts — they are not what the registry stores, and requesting them by that name returns `Artifact <name> not found`. The stored types are:

| Tier | Name | Type | Target |
|---|---|---|---|
| pack | `SCAM-027` | `campaign_pack` | `phone_worker` |
| pack | `SCAM-027_phishing_playbook_patch` | `phishing_playbook_patch` | `phishing_worker` |
| pack | `SCAM-027_txn_rule` | `txn_rule` | `financial_worker` |
| pack | `SCAM-027_cs_advisory` | `cs_advisory` | external, via MCP |
| pack | `SCAM-027_compliance_brief` | `compliance_brief` | external, via MCP |
| **core** | `phone_agent_core` | `phone_agent_core` | `phone_worker` |

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

## Step 9 — REPLAY mode (the recorded 5-act run)

> **Two different things are called "replay". Know which one you are using.**
>
> | | Server-side replay | The console's REPLAY button |
> |---|---|---|
> | Started by | `POST /enterprise/demo/replay/start` (or `POST /demo/scenario {mode:"replay"}`) | Clicking the REPLAY button, or pressing **M** |
> | Plays | The curated 25-frame acts I–V sequence in `backend/seeds/ns_events/replay_sequence.json` | The most recent ≤500 rows of `ns_events`, with their *real* recorded gaps |
> | Length | **18 s** at 1x (9 s at 2x) | Depends on how much history the log holds — **938 s ≈ 15.6 min** at 1x in a warmed-up demo |
> | Transport | Server broadcasts over the WebSocket | Console-side timer; the WebSocket is torn down |
> | Console must be | in **LIVE** (badge says LIVE) | in REPLAY |
>
> **For a timed pitch, use the server-side replay with the console left in LIVE.** The REPLAY button is not a 6-minute demo: it replays whatever the log happens to contain, idle time included, and it grows with every interaction.

### The timed arc

Leave the console in **LIVE** so the WebSocket is connected, then:

```bash
# Streams acts I–V in 18 seconds. Frames are broadcast but NOT persisted,
# so replaying does not pollute the event log.
curl -X POST http://localhost:8000/enterprise/demo/replay/start \
  -H "Content-Type: application/json" \
  -d '{"speed": 1}'
```

The console does **not** switch modes by itself — it receives these frames on its live WebSocket, so the nerve map, ticker and counters react exactly as they would to real events. The mode badge keeps saying `LIVE`, which is accurate: the transport really is live.

What the frames carry (25 total, tagged by act):

| Act | Frames | What you see |
|---|---|---|
| I — sensing | 9 | `case_ingested`, `mo_extracted`, `entity_linked` → Overview + Case detail |
| II — discovery | 5 | `cases_linked`, `case_observed`, `campaign_proposed` → Overview, Scam Graph |
| III — validation | 1 | `campaign_approved` → Validation |
| IV — compile | 8 | `compilation_completed`, `core_patch_proposed`, `artifact_published`, `core_artifact_published`, 4× `propagation_acknowledged` → Registry |
| V — proof | 2 | `mcp_call`, `eval_completed` → MCP Log, Evaluation |

```bash
# Check progress
curl http://localhost:8000/enterprise/demo/status | python3 -m json.tool

# Stop early
curl -X POST http://localhost:8000/enterprise/demo/replay/stop
```

### If you do want the button

Pressing **REPLAY** fetches the log slice and plays it client-side at 1x. Before using it on stage, check what you would be committing to:

```bash
curl -s "http://localhost:8000/enterprise/events?limit=500" \
  | python3 -c "import sys,json,datetime as d; e=json.load(sys.stdin)['events']; \
print(len(e),'events spanning', round((d.datetime.fromisoformat(e[-1]['ts'].replace('Z','+00:00'))-d.datetime.fromisoformat(e[0]['ts'].replace('Z','+00:00'))).total_seconds()),'s')"
```

If that prints minutes, don't press the button — use the server-side replay above. Press **M** or the button again to return to LIVE.

---

## Step 10 — Connect WorkBuddy as the Compliance department (MCP)

This is Act 5 of the demo: WorkBuddy (Tencent's agent) connects to TranSafe's MCP server as a `compliance` role, queries fraud intelligence, and the Liaison Agent answers with role-based redaction applied.

This is the point of the whole MCP layer: an **external system** — not our own console, a third-party agent — is asking TranSafe questions and getting answers that are structurally scoped to what it is entitled to see.

### What the compliance role can see

| Can see | Cannot see |
|---------|------------|
| Campaign details, MO fingerprints, indicators, artifacts, compliance briefs, case IDs, aggregate stats | Transcripts, victim names, phone numbers, account numbers, customer PII, raw case evidence |

Redaction is **server-side and structural** — it runs on the payload before the Liaison Agent sees it. WorkBuddy literally cannot read fields it's not entitled to. This is not a prompt instruction; it cannot be prompt-injected away.

### Step 10a: Ensure the backend is running

The MCP server uses the same Supabase connection and env vars as the backend. Make sure the backend is already running (Step 1) so the database is accessible.

### Step 10b: Add TranSafe as a custom MCP server in WorkBuddy

WorkBuddy reads MCP server config from **`~/.workbuddy-ai/mcp.json`**.

> **The filename matters.** It is `mcp.json`, **not** `.mcp.json` — WorkBuddy's own docs call this out, and a config placed at the wrong path fails silently: the server simply never appears.

Open it:

```bash
nano ~/.workbuddy-ai/mcp.json
```

Merge the `transafe` entry into the **existing** `mcpServers` object — do not replace the file, or you will clobber any other server you have configured:

```json
{
  "mcpServers": {
    "transafe": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp.server"],
      "cwd": "/Users/Admin/Documents/GitHub/Transafe/backend",
      "env": {
        "TRANSAFE_CALLER": "workbuddy",
        "TRANSAFE_ROLE": "compliance",
        "TRANSAFE_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Key settings:
- **`TRANSAFE_ROLE: "compliance"`** — this is the entitlement ceiling. WorkBuddy can request a narrower role per-call, but never a broader one. Launching with `compliance` and asking for `fraud_ops` gets you `compliance`.
- **`cwd`** — must point to your backend directory (where `uv` can find the project).
- **`TRANSAFE_CALLER: "workbuddy"`** — stamps every audit log entry so you can trace who called what. This is the value that appears in the console's `caller` column.

No `transport` key is needed — `command` implies stdio.

**Credentials are not needed here.** The server loads `backend/.env` itself on startup, so `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` do not belong in this file. Only the `TRANSAFE_*` keys go in, because they describe *how this client is being launched*, not what the server needs to run.

> If you ever see `Supabase client is not initialized` inside a WorkBuddy tool result, the `.env` did not load — check that `cwd` points at `backend/` and that `backend/.env` exists.

### Step 10b-ii: Trust the server (do not skip this)

Saving the file is **not** enough. WorkBuddy ships custom MCP servers **disabled** until you explicitly trust them, because an MCP server can execute code and touch your files.

1. **Restart WorkBuddy** so it re-reads `mcp.json`.
2. Open **connector management**.
3. Find the **custom connectors** entry at the top-right.
4. Click **Trust** on `transafe`.

Until you click Trust, the server stays switched off and no tool call will reach TranSafe. If Step 10c shows nothing happening, this is almost always why.

### Step 10c: Verify the connection

In a new WorkBuddy conversation, type:

```
List all active TranSafe campaigns
```

WorkBuddy should call the `list_active_campaigns` MCP tool. The MCP server will:
1. Check the rate limit (60/min)
2. Verify the `compliance` role is entitled to the `campaign` resource category
3. Fetch campaign data from Supabase
4. Run `redact_by_role()` on the payload — redacting transcript text, PII, phone numbers, account numbers
5. Return the redacted result to WorkBuddy
6. Write an audit entry to `mcp_access_log`
7. Emit an `exposure/mcp_call` ns_event (visible live on console Screen G)

**Verify the server side independently** if WorkBuddy shows no tools. This handshake proves the server itself is healthy and isolates any problem to the client config:

```bash
cd /Users/Admin/Documents/GitHub/Transafe/backend
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{}}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  | TRANSAFE_CALLER=workbuddy TRANSAFE_ROLE=compliance uv run python -m mcp.server
```

Expect `TranSafe MCP server ready (caller=workbuddy role=compliance)` followed by two JSON-RPC replies.

### Step 10d: Try these queries as compliance

In a WorkBuddy conversation, try these prompts:

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

To see how redaction changes by role, edit `~/.workbuddy-ai/mcp.json` and change `TRANSAFE_ROLE` to a different role, restart WorkBuddy, and ask the same questions:

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

While WorkBuddy makes MCP calls, have the Enterprise Console open in your browser at `http://localhost:5174/mcp`:

- **MCP Log screen** shows every call in real time: the tool name, the caller (`workbuddy`), the role (`compliance`), the response status, and which fields were redacted
- The **Overview screen** event ticker shows `exposure/mcp_call` events as they happen
- Every call — success, denial, rate-limit rejection, error — is logged. An audit log that only records successes is useless for exactly the incident you'd want to investigate

### Step 10g: Check the audit log via API

```bash
curl http://localhost:8000/enterprise/mcp/log | python3 -m json.tool
```

Each entry shows:
- `caller` — who called (e.g., `workbuddy`)
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
2. Deletes all rows from **13 v2 tables** — `ns_events`, `entities`, `case_entity_links`, `case_links`, `case_mo`, `case_discovery_state`, `campaigns`, `campaign_cases`, `artifacts`, `artifact_consumption`, `mcp_access_log`, `eval_runs`, `eval_results`
3. Re-seeds the demo corpus (16 cases, SCAM-019 + SCAM-024 approved, `phone_agent_core` v6)
4. Leaves v1 tables (`users`, `fraud_cases`, `call_transcripts`) untouched — the purge list is a module constant with no request-body injection point, and it is checked against the v1 table set at import time

> ## ⚠️ RESET is a one-way door
>
> It deletes the approved campaign, its five published artifacts **and the core `phone_agent_core` v7**. After a reset you are back to the pre-campaign opening position and must warm up again (seed → discovery ×2 → approve). Never press it once you have warmed up for a pitch.
>
> Two consequences that surprise operators:
>
> 1. **The header keeps counting historical cases.** Because v1 `fraud_cases` are deliberately never purged, the counter shows every case from every previous run. A warmed-up demo currently reads **`Cases 127`**, not 16. That is cosmetic, but do not promise a number on stage.
> 2. **The event log is emptied, so the REPLAY button has nothing to play.** Straight after a reset the log holds only the reset/seed events, and `loadReplaySequence` will fall through to the bundled fixture — which raises the `⚠ FIXTURE` badge. Warm up first, then replay.

The response tells you exactly what happened:

```json
{
  "ok": true,
  "message": "cleared 13 v2 table(s); corpus reseeded",
  "cleared": ["eval_results", "eval_runs", "artifact_consumption", "..."],
  "warnings": [],
  "reseed": { "status": "ok", "counts": { "users": 16, "campaigns": 2, "artifacts": 1 } }
}
```

---

## Full demo flow (quick reference)

```bash
# ── Terminal 1: Backend ──────────────────────────────
# No --reload: a mid-demo restart drops in-flight background tasks.
cd backend && uv run uvicorn main:app --host 127.0.0.1 --port 8000

# ── Terminal 2: Frontend ─────────────────────────────
cd frontend/enterprise && npm run dev
# Open http://localhost:5174

# ── Terminal 3: Demo commands ────────────────────────
# 1. Seed data
curl -X POST http://localhost:8000/enterprise/demo/seed

# 2. Run discovery TWICE — sweep 1 links the cases, sweep 2 promotes the cluster
curl -X POST http://localhost:8000/enterprise/discovery/run
curl -X POST http://localhost:8000/enterprise/discovery/run

# 3. Check campaigns
curl http://localhost:8000/enterprise/campaigns | python3 -m json.tool

# 4. Approve campaign (replace ID). generalise=true is what produces the
#    core-tier phone_agent_core v7 — omit it and you get the pack only.
curl -X POST http://localhost:8000/enterprise/campaigns/<ID>/approve \
  -H "Content-Type: application/json" -d '{"approved_by": "fraud_ops", "generalise": true}'

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

# 9. Connect WorkBuddy as compliance department
# Merge the transafe entry into ~/.workbuddy-ai/mcp.json (see Step 10)
# Restart WorkBuddy and click Trust on the custom connector, then ask:
#   "Tell me about TranSafe campaign SCAM-027"
```

---

## How the console works

### The mental model

**The console computes nothing. It is a viewer.**

```
   SOMETHING HAPPENS  ──►  writes a row to `ns_events`  ──►  the console redraws
   (a call, a command,       (the event log — the one          (WebSocket +
    or the replay)            channel everything shares)        per-screen refetch)
```

Every screen is a rendering of that log. So whenever you are unsure what a screen is doing, ask: *what is producing events right now?* There are only ever three answers:

| Producer | What it is | Used for |
|---|---|---|
| **The real pipeline** | A live call, a phishing submission, a transaction. v1 runs first; v2 runs after it | The booth — a judge tries their own scam |
| **Operator commands** | `demo/seed`, `discovery/run`, `campaigns/:id/approve`, `eval/run` | Warm-up and the interactive beats |
| **The recorded replay** | The server streams the curated 25-frame act sequence over the WebSocket | The timed arc, when live API calls are too risky |

Screens never poll. Each one loads once on mount, then refetches **only when a relevant real event arrives**.

### Header controls

| Control | Shortcut | What it actually does |
|---|---|---|
| **Mode badge** `LIVE` / `REPLAY` | — | Not a setting, a report: which event source the console is bound to. The dot beside it shows WebSocket health |
| **REPLAY ⇄ LIVE** | **M** | LIVE→REPLAY: fetches the recent log slice, tells the server to start its replay, tears down the WebSocket and plays the slice client-side with real gaps. REPLAY→LIVE: clears the buffer and reconnects the WebSocket. **Not a timed-demo control** — see Step 9 |
| **▶ RUN SCENARIO** | — | In LIVE: `POST /demo/scenario {mode:"live"}` → stops any server-side replay and returns to live. In REPLAY: re-fetches and restarts the client-side playback |
| **↺ RESET** | **R** | Purges the 13 v2 tables, reseeds, and destroys the approved campaign, its artifacts and core v7. One-way door |
| **⚠ FIXTURE** | — | Appears the moment any request fails and fabricated fixture data is rendered in its place. **Sticky and never cleared.** If you see it, the screen is not showing the real system — restore the backend and reload |

### Screens

| Screen | Path | Purpose | Loads | Refetches on | Point at |
|---|---|---|---|---|---|
| **Overview** | `/` | Presentation screen | `GET /overview` | `case_ingested`, `campaign_proposed`, `campaign_approved`, `artifact_published` | The nerve map pulsing, and `⚠ Unrecognised` in the header |
| **Cases** | `/cases`, `/cases/:id` | The Living Case | `GET /cases`, `GET /cases/:id` | `case_ingested` | The novel phrase highlighted on its exact transcript line |
| **Scam Graph** | `/graph` | The knowledge graph | `GET /graph` | graph-relevant events | Hover an edge — it states why those two cases are linked |
| **Validation** | `/validation` | The human gate | `GET /campaigns` (+ `PATCH` to edit) | `campaign_proposed`, `campaign_approved`, `campaign_rejected` | Computed evidence on the **left**, LLM hypothesis on the **right** |
| **Registry** | `/registry` | Artifact versions | `GET /artifacts`, `GET /artifacts/:name/:version` | registry and compiler events | The **CORE** tab's v6→v7 diff; the **CAMPAIGN PACKS** tab grows, CORE barely moves |
| **Evaluation** | `/eval` | Measured before/after | `GET /eval/latest` (+ `POST /eval/run`) | `eval_completed` | The false-positive row deliberately staying flat |
| **MCP Log** | `/mcp` | External access audit | `GET /mcp/log?as_role=…` | `mcp_call` | The role selector — same question, different fields redacted |

### The role selector (MCP Log)

Changing the role re-requests the log *as that role* and shows what each one would have received. `fraud_ops` sees everything; `compliance` loses transcripts and PII; `partner_bank` loses case ids and customer data; `public` sees aggregates only. Redaction happens server-side before synthesis, so an external agent cannot talk its way past it.

### Keyboard

| Key | Action |
|---|---|
| **M** | Toggle LIVE ⇄ REPLAY |
| **R** | Reset (destructive — see the warning above) |

Both are ignored while typing in an input.

### Pre-flight, before the audience arrives

Run this every time. Each line exists because it bit us during testing.

```bash
# 1. Kill stale servers. A leftover backend on :8000 running older code is the
#    single most confusing failure: the console loads, but renders stale or
#    empty data, because curl and the browser proxy reach the old process.
ps -eo pid,command | grep -E 'uvicorn|vite' | grep -v grep

# 2. Start the backend WITHOUT --reload. Reload can restart the process
#    mid-demo and drop in-flight background tasks (compile, propagate).
cd backend && uv run uvicorn main:app --host 127.0.0.1 --port 8000

# 3. Start the console
cd frontend/enterprise && npm run dev -- --port 5174

# 4. Warm up: reset, discovery TWICE, approve with generalise
curl -X POST localhost:8000/enterprise/demo/reset -H 'Content-Type: application/json' -d '{"reseed":true}'
curl -X POST localhost:8000/enterprise/discovery/run
curl -X POST localhost:8000/enterprise/discovery/run
curl -X POST localhost:8000/enterprise/campaigns/<ID>/approve \
  -H 'Content-Type: application/json' -d '{"approved_by":"fraud_ops","generalise":true}'

# 5. Confirm the artefact chain landed
curl -s localhost:8000/enterprise/artifacts | python3 -c "import sys,json;print([(a['tier'],a['name'],a['version']) for a in json.load(sys.stdin)['artifacts']])"
```

Then, **in the browser**:

1. Load the console and **give the header a moment to populate** (~0.5 s locally). It shows `—` during first paint, which is normal — do not reload, and do not start talking over an unpopulated header.
2. Confirm the mode badge reads **LIVE** and its dot is lit (WebSocket connected).
3. Confirm **no `⚠ FIXTURE` badge**. That badge — not a momentary `—` — is the only reliable sign that fabricated data is on screen.
4. Confirm the Registry **CORE** tab shows `phone_agent_core → phone_worker` at **v7** with `v6 → v7 · +2/-0` in the diff.
5. Only then start the replay (Step 9).

**Do not press RESET after this point.**

---

## Troubleshooting

### "ns_events table: MISSING"

The migration hasn't been applied. See Prerequisites §3.

### Frontend shows blank screen / no WebSocket data

1. Check backend is running: `curl http://localhost:8000/health`
2. Check WebSocket proxy: open browser DevTools → Network → WS. You should see a connection to `/enterprise/ws/events`.
3. The Vite proxy config forwards `/enterprise` to `http://localhost:8000` with `ws: true`.
4. If `[vite] ws proxy error: ECONNREFUSED` fills the dev-server log, the backend simply is not up. That message means "nothing is listening", not "the proxy is misconfigured".

### The header counters show `—` for a moment after loading

**This is expected first paint, not a fault.** The console issues its initial requests on mount and the header populates when they resolve — measured at **~0.5 s** on a local backend. A screenshot or a glance taken *during* that window shows `—` everywhere and an empty Registry, which looks broken but is not.

- **Do not reload.** Wait a moment; the counters appear on their own.
- If they are still `—` after several seconds, *then* investigate:
  - `curl http://localhost:8000/enterprise/overview` — confirm the API answers.
  - Check the browser console for a failed request.
- If the `⚠ FIXTURE` badge is present, a request genuinely failed and fabricated data is on screen. Restore the backend and reload. This badge is the reliable signal — absence of counters is not.

### "counts": 0 after seeding

The seed likely hit a migration issue. Check for warnings in the response:

```bash
curl -X POST http://localhost:8000/enterprise/demo/seed | python3 -m json.tool
```

Look at the `"warnings"` array — it will name the table and error.

### Discovery produces no campaigns

- **Run the sweep twice.** This is the cause in almost every case: one sweep after a reset links the cases but does not promote a candidate. The command returns `{"status":"started"}` either way, so it *looks* successful.
- Ensure you seeded first (`/enterprise/demo/seed`) and that the response reported `campaigns: 2` and `artifacts: 1`.
- The wave needs ≥3 cases sharing entities, ≥2 distinct customers, and at least one edge ≥0.80.
- Check the links directly: `curl http://localhost:8000/enterprise/graph | python3 -m json.tool`. Six wave cases should be mutually linked at scores 0.9–1.0.
- The endpoint is asynchronous. Give the second sweep a few seconds before concluding it failed.

### DeepSeek API errors

- Verify `DEEPSEEK_API_KEY` is set: `echo $DEEPSEEK_API_KEY` (or check `.env`)
- The system has a structural regex fallback for MO extraction when the API key is dead, so core functionality works without it
- Embeddings use a deterministic local fallback when `DASHSCOPE_API_KEY` is missing — the demo runs fine without DashScope
- Artifact compilation will use fallback templates if DeepSeek is unreachable

### Port conflicts

- Backend: `uv run uvicorn main:app --port 8080` (then point the Vite proxy at 8080).
- Frontend: Vite is configured for 5174 but **does not fail if it is taken — it silently moves to 5175 and prints the new URL.** If the console looks wrong, check the dev-server banner for the actual port before assuming a bug. Kill leftover `vite` processes first.

---

## What each step demonstrates

| Step | Build Block | What it proves |
|------|-------------|----------------|
| Seed | B0, B1 | DB schema works, MO fingerprints + entities load |
| Discovery | B2 | Linkage, clustering, campaign detection — the core product |
| Approve | B4, B4b, B5 | Compiler produces artifacts, generaliser extracts core tier, propagation pushes to workers |
| Artifacts | B4 | Registry stores, versions, diffs artifacts |
| Evaluation | B7, B7b | Before/after metrics, adaptation loop closes the gap |
| Replay | B9 | The curated 5-act recorded run streams over the WebSocket (server-side). The console's REPLAY button instead plays the live log slice — see Step 9 |
| MCP | B6 | External agent queries TranSafe safely with role-based redaction |
| Reset | B9 | Clean reset for re-runs without touching v1 data |
