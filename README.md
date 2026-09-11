# 🛡️ TranSafe

**AI CAN DO IT Tencent Cloud X UTM Hackathon**
**Team**: SleepWell
**Video Pitch**: [Watch on YouTube](https://youtu.be/bDpos5liC_E)
**Live Demo** (v1 app): [https://transafe123.netlify.app/](https://transafe123.netlify.app/)

---

TranSafe protects retail banking customers from fraud in real time — fusing transactions, behavioural telemetry, live phone calls and phishing material through a multi-agent AI system that intervenes while the scam is still in progress. Unlike a static rule engine, it discovers new fraud campaigns on its own, red-teams its own defences to find the gaps, and writes the detection rules that close them — measured, not claimed.

> **New here?** The v1 platform below is the original submission. The **v2 Enterprise layer** ([jump to it](#-v2-enterprise-layer--whats-new)) is the upgrade: autonomous campaign discovery, a self-improving defence loop, and a role-redacted MCP gateway. Its console is a separate app from the deployed v1 demo.

## ✨ Key Features

* **🧠 Multi-Agent Orchestration** — specialised agents (Financial, Telemetry, Research, Phone, Phishing) run in parallel to assess risk, avoiding monolithic-LLM bloat and cutting latency.
* **📞 Live Call Interception (Auto-Talk)** — real-time audio over WebSockets with streaming STT. TranSafe can passively listen for coercion markers or autonomously converse with the scammer.
* **🏃‍♂️ Passive Behavioural Telemetry** — detects device takeover or physical coercion (dictation, screen sharing) from typing cadence and navigation behaviour.
* **🌐 Adaptive Fraud Memory (RAG)** — Supabase `pgvector` cross-references extracted entities (phone numbers, URLs, accounts) against a growing knowledge base of playbooks and public reports via Tavily.
* **⚖️ Explainable AI (XAI)** — bilingual narratives explaining *why* an action (e.g. a 30-minute cooling-off freeze) was taken.

---

## 🚀 v2 Enterprise Layer — What's New

v1 decides about **one event at a time**. v2 asks the harder questions: *are these events one campaign? what should we have learned? who else needs to know?* Four blocks, each with its own design doc in [`doc/transafe_v2/`](doc/transafe_v2):

| Block | Module | What it does |
|---|---|---|
| **Discovery** | `backend/src/enterprise/discovery.py` | Clusters cases that share an MO into a campaign nobody reported. Allocates the next free code (`SCAM-027`) rather than a row count. |
| **Artifact Registry** | `registry.py`, `propagation.py` | Versioned defence artifacts (`phone_agent_core`, region packs). Publishing bumps the version and propagates it to each worker, which writes a receipt — so a receipt means a consumer actually *read* it. Rollback is a first-class action. |
| **Adaptation loop** | `adaptation.py` | The blue team. Scores the corpus, generalises a structural rule from the misses, auto-approves it only if measured confidence clears the threshold, re-publishes, re-scores. |
| **MCP Gateway** | `backend/mcp/` | A hand-rolled JSON-RPC 2.0 server over stdio, exposing 8 tools to external agents with **server-side, structural** role redaction, rate limiting and an audit log. |

### The headline result

The evaluation corpus is 20 wave variants, **10 adversarial red-team mutations**, and 10 legitimate controls. After the adaptation loop runs one cycle:

| | base (20) | red-team (10) | false positives |
|---|---|---|---|
| Published core | 0.90 | **0.20** | 0/10 |
| After one adaptation cycle | **1.00** | **0.90** | 0/10 |

The system found its own gap, wrote one structural rule, and closed it — with **no new false positives**. Both numbers are produced by the harness, not asserted in a slide.

### The Enterprise Console

A separate React app (`frontend/enterprise`) with seven screens, all rendering one table — `ns_events`. The console computes nothing; it renders what the system emitted.

| Screen | Path | Shows |
|---|---|---|
| Overview | `/` | Nerve map, live event feed, time-to-discovery |
| Cases | `/cases` | Ingested cases and their discovery state |
| Scam Graph | `/graph` | Entities, links and campaign clusters |
| Validation | `/validation` | The human decision gate: approve or reject a candidate |
| Registry | `/registry` | Artifact versions, diffs, rollback, propagation receipts |
| Evaluation | `/eval` | Base vs **red-team** detection, false positives, before/after |
| MCP Log | `/mcp` | Every external MCP call, its role, and what was redacted |

---

## 🏗️ Architecture

TranSafe's core is an event-driven directed state machine built with **LangGraph**:

1. **Trigger** — app events (`TRANSACTION`, `CALL`, `TELEMETRY`, `PHISHING`) hit the FastAPI backend.
2. **Orchestration** — the Orchestrator delegates context to parallel worker agents.
3. **Execution** — agents gather data from Supabase, evaluate via the LLM, and append findings to a shared `GraphState`.
4. **Enforcement** — a Risk Scorer aggregates weighted findings into a tier (LOW/MEDIUM/HIGH); the Action Dispatcher approves, challenges or freezes.
5. ***(v2)* Learning** — Discovery clusters cases into campaigns; validated decisions become registry artifacts that propagate back into the workers.

## 🧰 Agents' Skills

Behavioural guardrails are loaded from markdown in `backend/skills/` (e.g. `phone_dialogue_guide.md`, `anchor_questions.md`) and injected into each agent's system prompt, so policy changes do not require a redeploy.

## 🛠️ Technology Stack

| Layer | Choice |
|---|---|
| **Backend** | FastAPI, uvicorn, LangGraph, Pydantic |
| **Inference** | DeepSeek (`deepseek-chat`) via `langchain-openai` |
| **Embeddings** | Alibaba DashScope `text-embedding-v3` (768-dim) |
| **Data** | Supabase (PostgreSQL, `pgvector`, REST) |
| **Voice** | Streaming STT, Edge-TTS / ElevenLabs, vision OCR |
| **External search** | Tavily |
| **Interop** | Model Context Protocol (MCP), stdio JSON-RPC 2.0 |
| **Frontend** | React + TypeScript + Vite, Zustand, Recharts, react-force-graph |

> **Model note.** `deepseek-chat` is served by the API as `deepseek-flash` in **non-thinking** mode — fast and cheap. Requesting `deepseek-flash` or `deepseek-v4-pro` *by name* enables reasoning, which is several times slower and can return an **empty answer** if the token budget is spent thinking. Leave `DEEPSEEK_MODEL_PRIMARY=deepseek-chat`. The console's readiness check warns if you change it.

---

## 🏁 How to Run

### 0. Prerequisites

* Python 3.13 and [`uv`](https://docs.astral.sh/uv/)
* Node.js 20+
* A Supabase project, plus API keys for DeepSeek and DashScope

### 1. Configure the backend

Create `backend/.env`:

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_KEY=<service-role-key>
DEEPSEEK_API_KEY=<key>
DEEPSEEK_MODEL_PRIMARY=deepseek-chat     # non-thinking — see the model note above
DASHSCOPE_API_KEY=<key>
```

### 2. Apply the database schema

Open the Supabase **SQL Editor** and run, in order:

1. `backend/migrations/003_adaptive_case_labeling.sql`
2. `backend/migrations/v2_enterprise.sql` ← the v2 layer needs this

There is no CLI path for this; the dashboard is the only supported route.

### 3. Start the backend

```bash
cd backend
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

> Run it from `backend/`, or use `uv run --project backend uvicorn main:app --app-dir backend`. A `cd backend` from *inside* `backend/` fails.

Confirm it is alive: `curl http://127.0.0.1:8000/health` → `200`.

### 4. Start the Enterprise Console

```bash
npm --prefix frontend/enterprise install
npm --prefix frontend/enterprise run dev -- --port 5174
```

Open **http://localhost:5174**. The dev server proxies `/enterprise` to `localhost:8000`, so the backend must be running. Without `--strictPort`, Vite will silently move to 5175 if 5174 is taken.

*The v1 app* is separate: `npm --prefix frontend/transafe run dev` (port 5173). That is what Netlify deploys.

### 5. (Optional) Connect an external agent over MCP

The MCP server is **stdio only** — there is no port and nothing to start. A client launches it as a subprocess.

Merge this into `~/.workbuddy-ai/mcp.json`, into the **existing** `mcpServers` object:

```json
{
  "mcpServers": {
    "transafe": {
      "command": "/absolute/path/to/Transafe/backend/.venv/bin/python",
      "args": ["-m", "mcp.server"],
      "cwd": "/absolute/path/to/Transafe/backend",
      "env": {
        "TRANSAFE_CALLER": "workbuddy",
        "TRANSAFE_ROLE": "compliance",
        "TRANSAFE_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Then **restart WorkBuddy** and click **Trust** on the server under connector management → custom connectors. It ships disabled, and until you trust it no call reaches TranSafe.

A ready-to-paste copy lives at [`backend/mcp/workbuddy_config.json`](backend/mcp/workbuddy_config.json).

> **Use the venv interpreter, not `uv`.** A GUI-launched client does not inherit your shell `PATH`, so `"command": "uv"` fails with `uv: No such file or directory`. Credentials stay out of this file — the server loads `backend/.env` itself.

---

## 🎬 Running the Demo

Open the console, click **PREP** in the header, then:

1. **CHECK READINESS** — verifies Supabase, the v2 schema, the core artifact, the MCP tool surface and the model, and names anything broken.
2. **PREPARE DEMO** — one click runs `reset → discovery → discovery` (the first sweep does not promote; the second does) and turns green when a candidate campaign is ready.

Then walk the screens: approve the candidate on **Validation**, watch the version bump on **Registry**, run the blue-team loop on **Evaluation**, and trigger a live MCP call from WorkBuddy while **MCP Log** is open.

The full script, timings and failure fallbacks are in **[doc/transafe_v2/DEMO_GUIDE.md](doc/transafe_v2/DEMO_GUIDE.md)**.

Two operational notes: the header counters take a few seconds to populate on a cold load, so click through every screen **before** an audience arrives; and `R` / `M` are global hotkeys — `R` resets the demo.

---

## 🧪 Tests

```bash
# Backend — 743 unit tests, no network, no API keys
cd backend && uv run pytest tests/unit/ -q

# Frontend — 212 tests (runs tsc first)
npm --prefix frontend/enterprise test

# Lint
cd backend && uv run ruff check src/enterprise/ mcp/
npm --prefix frontend/enterprise run lint
```

---

## 📖 Documentation

[`doc/transafe_v1/`](doc/transafe_v1) — the original platform

* [01_PRD.md](doc/transafe_v1/01_PRD.md) · [02_architecture.md](doc/transafe_v1/02_architecture.md) · [03_agent_flow.md](doc/transafe_v1/03_agent_flow.md)
* [04_api_design.md](doc/transafe_v1/04_api_design.md) · [05_database_schema.md](doc/transafe_v1/05_database_schema.md) · [06_deployment_guide.md](doc/transafe_v1/06_deployment_guide.md)
* [07_backend_implementation.md](doc/transafe_v1/07_backend_implementation.md) · [08_detailed_design.md](doc/transafe_v1/08_detailed_design.md) · [09_updates_changelog.md](doc/transafe_v1/09_updates_changelog.md)

[`doc/transafe_v2/`](doc/transafe_v2) — the Enterprise layer

* [01_upgrade_plan.md](doc/transafe_v2/01_upgrade_plan.md) · [IMPLEMENTATION_PROMPT.md](doc/transafe_v2/IMPLEMENTATION_PROMPT.md)
* [02_discovery_design.md](doc/transafe_v2/02_discovery_design.md) · [03_artifact_registry.md](doc/transafe_v2/03_artifact_registry.md)
* [04_mcp_gateway.md](doc/transafe_v2/04_mcp_gateway.md) · [05_frontend_spec.md](doc/transafe_v2/05_frontend_spec.md)
* [07_evaluation.md](doc/transafe_v2/07_evaluation.md) · [06_demo_runbook.md](doc/transafe_v2/06_demo_runbook.md)
* **[DEMO_GUIDE.md](doc/transafe_v2/DEMO_GUIDE.md)** — the operator's script

---

## 💬 Chat Logs

[code_buddy_chat_log/history_202607261708.md](code_buddy_chat_log/history_202607261708.md)
