# TranSafe Overall Progress

## Module 1: Database & Memory Persistence Layer (`src/db/`)
- [x] Implement `init_supabase` and connection manager (`src/db/supabase.py`).
- [x] Implement `fetch_telemetry_events` query with 1-hour lookback.
- [x] Implement `fetch_user_transaction_history` (90-day aggregation, amounts, known recipients).
- [x] Implement `fetch_case_context` (fetching transcripts, phishing content, case entities).
- [x] Implement `insert_fraud_case` and `update_fraud_case_status`.
- [x] Implement `insert_call_transcript`.
- [x] Implement `insert_case_entities` and `insert_phishing_submission`.
- [x] Implement `update_transaction_status` (e.g., freezing with `unfreeze_at`).
- [x] Implement `insert_admin_alert`.
- [x] Implement `init_vector_store` for pgvector (`src/db/vector_store.py`).
- [x] Implement `embed_text` using Groq API (`nomic-embed-text-v1.5`).
- [x] Implement `search_fraud_memory` calling Supabase RPC.
- [x] Implement `add_fraud_memory` (embedding content and inserting to pgvector).
- [x] Implement `check_blacklist` (wrapper over `search_fraud_memory` with high threshold > 0.80).
- [x] Implement database seed script `seeds/seed_db.py` to generate mock users, accounts, transactions, and fraud memory.
- [x] Write unit tests for DB layer operations (`tests/unit/test_db.py`).

## Module 2: External Integration Services (`src/services/`)
- [x] Implement `extract_text_from_image` using Groq Vision (`llama-3.2-11b-vision-preview`).
- [x] Implement `transcribe_audio_chunk` using Groq Whisper (`whisper-large-v3`).
- [x] Implement `synthesize_text_to_audio` using `edge-tts` (`en-SG-LunaNeural` / `ms-MY-YasminNeural`).
- [x] Implement `tavily_search` focusing on Malaysian domains (`semak.my`, `rmp.gov.my`, `bnm.gov.my`, `lowyat.net`).
- [x] Write unit tests for services with mocked external API calls (`tests/unit/test_services.py`).

## Module 3: Dynamic Skills & Prompt Management (`src/agents/prompts.py`)
- [x] Implement `load_skill_file` to read markdown skill definitions from `backend/skills/`.
- [x] Implement `get_phone_dialogue_guide` for Phone Worker Auto-Talk mode.
- [x] Implement `get_anchor_questions` parsing logic.
- [x] Build prompt formatting for `telemetry_worker` (handling session metrics, biometrics, network fingerprint).
- [x] Build prompt formatting for `financial_worker` (handling pending tx, 90-day baseline, case context overrides).
- [x] Build prompt formatting for `research_worker` (handling QUERY mode and INGEST mode).
- [x] Build prompt formatting for `phishing_worker` (handling TEXT, URL, IMAGE sources).
- [x] Build prompt formatting for `phone_worker` real-time utterance highlighter (LISTEN mode).
- [x] Write unit tests for prompt parsing and generation (`tests/unit/test_skills.py`).

## Module 4: Worker Agents (`src/agents/workers/`)
- [x] Define `WorkerFinding` Pydantic models.
- [x] Implement `telemetry_worker_node` logic (detecting anomalies in flight times, tab switches, device fingerprint).
- [x] Implement `financial_worker_node` logic (anomalous patterns, amounts, timing, cross-checking active case context).
- [x] Implement `research_worker_node` logic (QUERY mode: pgvector + Tavily fallback; INGEST mode: fraud report summarisation).
- [x] Implement `phishing_worker_node` logic (entity extraction, deep content analysis).
- [x] Implement `phone_worker_node` real-time highlighter (Listen Mode — keyword fast pass + LLM span detection).
- [x] Implement `phone_worker_node` dialogue controller (Auto-Talk Mode — conversation state machine).
- [x] Write unit tests for each worker node function (`tests/unit/test_workers.py`).

## Module 5: Graph Orchestration & State Machine (`src/agents/`)
- [x] Define exact `GraphState` TypedDict as per design (`src/agents/state.py`).
- [x] Implement `orchestrator_node` logic (loading `associated_case_context` and determining routing).
- [x] Implement simplified routing for REPORT (Research INGEST mode direct path).
- [x] Implement two-stage routing for PHISHING (Phishing Analyst Stage 1 -> Research Stage 2).
- [x] Implement parallel worker activation for TRANSACTION, CALL, TELEMETRY.
- [x] Implement `risk_scorer_node` to calculate weighted risk score and normalise based on active workers.
- [x] Implement `xai_node` to generate explainable AI JSON report.
- [x] Implement `action_dispatcher_node` to resolve tier-based actions (LOW: approve, MEDIUM: biometric_challenge, HIGH: freeze).
- [x] Implement LangGraph graph compilation tying edges and nodes together (`src/agents/graph.py: compile_graph`).
- [x] Write unit tests for graph state machine and orchestration logic (`tests/unit/test_graph.py`).

## Module 6: REST API & WebSockets Layer (`src/api/` & `main.py`)
- [x] Setup FastAPI `main.py` with CORS, initialization callbacks, and LangGraph compilation.
- [x] Implement `verify_api_key` dependency.
- [x] Implement REST `POST /api/v1/trigger/telemetry` endpoint.
- [x] Implement REST `POST /api/v1/trigger/transaction` endpoint.
- [x] Implement REST `POST /api/v1/trigger/call` endpoint.
- [x] Implement REST `POST /api/v1/trigger/phishing` endpoint.
- [x] Implement REST `POST /api/v1/trigger/report` endpoint.
- [x] Implement REST `POST /api/v1/biometric/result` endpoint (callback handler).
- [x] Implement REST `POST /api/v1/call/{session_id}/takeover` endpoint.
- [x] Implement REST `GET /api/v1/cases/recent` endpoint.
- [x] Implement main pipeline WebSocket `/ws/session/{session_id}` (streaming agent status and final XAI result).
- [x] Implement phone audio WebSocket `/ws/call/{call_session_id}/audio` (binary WebM/Opus streaming).
- [x] Implement phone events WebSocket `/ws/call/{call_session_id}/events` (streaming live highlights and pre-checks).
- [x] Implement Admin REST endpoints (`/admin/v1/...`) for dashboard integration.
- [x] Write API integration and unit tests using `TestClient` (`tests/unit/test_api.py`).
