# TranSafe Overall Progress

## Module 1: Database & Memory Persistence Layer (`src/db/`)
- [ ] Implement `init_supabase` and connection manager (`src/db/supabase.py`).
- [ ] Implement `fetch_telemetry_events` query with 1-hour lookback.
- [ ] Implement `fetch_user_transaction_history` (90-day aggregation, amounts, known recipients).
- [ ] Implement `fetch_case_context` (fetching transcripts, phishing content, case entities).
- [ ] Implement `insert_fraud_case` and `update_fraud_case_status`.
- [ ] Implement `insert_call_transcript`.
- [ ] Implement `insert_case_entities` and `insert_phishing_submission`.
- [ ] Implement `update_transaction_status` (e.g., freezing with `unfreeze_at`).
- [ ] Implement `insert_admin_alert`.
- [ ] Implement `init_vector_store` for pgvector (`src/db/vector_store.py`).
- [ ] Implement `embed_text` using Groq API (`nomic-embed-text-v1.5`).
- [ ] Implement `search_fraud_memory` calling Supabase RPC.
- [ ] Implement `add_fraud_memory` (embedding content and inserting to pgvector).
- [ ] Implement `check_blacklist` (wrapper over `search_fraud_memory` with high threshold > 0.80).
- [ ] Implement database seed script `seeds/seed_db.py` to generate mock users, accounts, transactions, and fraud memory.
- [ ] Write unit tests for DB layer operations (`tests/unit/test_db.py`).

## Module 2: External Integration Services (`src/services/`)
- [ ] Implement `extract_text_from_image` using Groq Vision (`llama-3.2-11b-vision-preview`).
- [ ] Implement `transcribe_audio_chunk` using Groq Whisper (`whisper-large-v3`).
- [ ] Implement `synthesize_text_to_audio` using `edge-tts` (`en-SG-LunaNeural` / `ms-MY-YasminNeural`).
- [ ] Implement `tavily_search` focusing on Malaysian domains (`semak.my`, `rmp.gov.my`, `bnm.gov.my`, `lowyat.net`).
- [ ] Write unit tests for services with mocked external API calls (`tests/unit/test_services.py`).

## Module 3: Dynamic Skills & Prompt Management (`src/agents/prompts.py`)
- [ ] Implement `load_skill_file` to read markdown skill definitions from `backend/skills/`.
- [ ] Implement `get_phone_dialogue_guide` for Phone Worker Auto-Talk mode.
- [ ] Implement `get_anchor_questions` parsing logic.
- [ ] Build prompt formatting for `telemetry_worker` (handling session metrics, biometrics, network fingerprint).
- [ ] Build prompt formatting for `financial_worker` (handling pending tx, 90-day baseline, case context overrides).
- [ ] Build prompt formatting for `research_worker` (handling QUERY mode and INGEST mode).
- [ ] Build prompt formatting for `phishing_worker` (handling TEXT, URL, IMAGE sources).
- [ ] Build prompt formatting for `phone_worker` real-time utterance highlighter (LISTEN mode).
- [ ] Write unit tests for prompt parsing and generation (`tests/unit/test_skills.py`).

## Module 4: Worker Agents (`src/agents/workers/`)
- [ ] Define `WorkerFinding` Pydantic models.
- [ ] Implement `telemetry_worker_node` logic (detecting anomalies in flight times, tab switches, device fingerprint).
- [ ] Implement `financial_worker_node` logic (anomalous patterns, amounts, timing, cross-checking active case context).
- [ ] Implement `research_worker_node` logic (QUERY mode: pgvector + Tavily fallback; INGEST mode: fraud report summarisation).
- [ ] Implement `phishing_worker_node` logic (entity extraction, deep content analysis).
- [ ] Implement `phone_worker_node` real-time highlighter (Listen Mode — keyword fast pass + LLM span detection).
- [ ] Implement `phone_worker_node` dialogue controller (Auto-Talk Mode — conversation state machine).
- [ ] Write unit tests for each worker node function (`tests/unit/test_workers.py`).

## Module 5: Graph Orchestration & State Machine (`src/agents/`)
- [ ] Define exact `GraphState` TypedDict as per design (`src/agents/state.py`).
- [ ] Implement `orchestrator_node` logic (loading `associated_case_context` and determining routing).
- [ ] Implement simplified routing for REPORT (Research INGEST mode direct path).
- [ ] Implement two-stage routing for PHISHING (Phishing Analyst Stage 1 -> Research Stage 2).
- [ ] Implement parallel worker activation for TRANSACTION, CALL, TELEMETRY.
- [ ] Implement `risk_scorer_node` to calculate weighted risk score and normalise based on active workers.
- [ ] Implement `xai_node` to generate explainable AI JSON report.
- [ ] Implement `action_dispatcher_node` to resolve tier-based actions (LOW: approve, MEDIUM: biometric_challenge, HIGH: freeze).
- [ ] Implement LangGraph graph compilation tying edges and nodes together (`src/agents/graph.py: compile_graph`).
- [ ] Write unit tests for graph state machine and orchestration logic (`tests/unit/test_graph.py`).

## Module 6: REST API & WebSockets Layer (`src/api/` & `main.py`)
- [ ] Setup FastAPI `main.py` with CORS, initialization callbacks, and LangGraph compilation.
- [ ] Implement `verify_api_key` dependency.
- [ ] Implement REST `POST /api/v1/trigger/telemetry` endpoint.
- [ ] Implement REST `POST /api/v1/trigger/transaction` endpoint.
- [ ] Implement REST `POST /api/v1/trigger/call` endpoint.
- [ ] Implement REST `POST /api/v1/trigger/phishing` endpoint.
- [ ] Implement REST `POST /api/v1/trigger/report` endpoint.
- [ ] Implement REST `POST /api/v1/biometric/result` endpoint (callback handler).
- [ ] Implement REST `POST /api/v1/call/{session_id}/takeover` endpoint.
- [ ] Implement REST `GET /api/v1/cases/recent` endpoint.
- [ ] Implement main pipeline WebSocket `/ws/session/{session_id}` (streaming agent status and final XAI result).
- [ ] Implement phone audio WebSocket `/ws/call/{call_session_id}/audio` (binary WebM/Opus streaming).
- [ ] Implement phone events WebSocket `/ws/call/{call_session_id}/events` (streaming live highlights and pre-checks).
- [ ] Implement Admin REST endpoints (`/admin/v1/...`) for dashboard integration.
- [ ] Write API integration and unit tests using `TestClient` (`tests/unit/test_api.py`).
