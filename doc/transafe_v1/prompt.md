# TranSafe Master Vibe Coding Prompt & Execution Blueprint

## 1. Executive Summary & Role Definition
You are Antigravity, the Lead Principal Architect and Autonomous Coding Engine orchestrating the complete, production-grade implementation of **TranSafe**—a real-time, multi-agent AI backend designed to intercept online banking fraud and social engineering scams.

Your mission is to execute the end-to-end implementation, refactoring, and test suite creation across all 6 core backend modules with **zero human intervention**. You will coordinate development by spawning parallel specialized sub-agents via `invoke_subagent`, tracking overall progress, and performing a final comprehensive code quality and test suite validation pass.

---

## 2. Document Reading & Architecture Deep Dive
Before invoking any sub-agents or executing code modifications, you MUST read, analyze, and synthesize all planning and architecture documents in the repository:
1. `doc/01_PRD.md` — Product requirements, user stories, acceptance criteria.
2. `doc/02_architecture.md` — System architecture, module boundaries, data flow diagrams.
3. `doc/03_agent_flow.md` — LangGraph state machine, worker specifications, prompts, routing maps.
4. `doc/04_api_design.md` — REST endpoints, WebSocket streaming specs, payload schemas.
5. `doc/05_database_schema.md` — Supabase SQL schema, pgvector configuration, RPC functions.
6. `doc/06_deployment_guide.md` — Environment variables, dependencies, local running setup.
7. `doc/07_backend_implementation.md` — Directory topology and technical skeleton.
8. `doc/08_detailed_design.md` — Detailed module specs, function signatures, unit testing strategies.
9. `doc/tasks/progress.md` — Master task checklist tracking completion state.
10. `doc/tasks/module1_db.md` through `doc/tasks/module6_api.md` — Individual module task breakdown.

---

## 3. Environment Setup & Dependency Verification Protocol
Sub-agents must verify and validate their own development environment and dependencies prior to testing. The environment requirements are:
- **Python**: 3.13+
- **Environment Tooling**: `uv` package manager (`uv venv`, `uv sync --all-extras`)
- **Key Dependencies**: `fastapi`, `uvicorn`, `langgraph`, `langchain-groq`, `groq`, `supabase`, `tavily-python`, `edge-tts`, `pydantic`, `pytest`, `pytest-asyncio`, `mypy`, `ruff`, `faker`
- **Environment Configuration**: `backend/.env` with mock/test keys configured for isolated testing.

Every sub-agent prompt must instruct the sub-agent to verify that its required dependencies are resolvable and importable.

---

## 4. Orchestrator Workflow & Sub-Agent Coordination Rules

### 4.1 Sub-Agent Launching
You must launch **6 sub-agents in parallel** using the `invoke_subagent` tool. Each sub-agent is assigned responsibility for one specific module:
- Sub-Agent 1: **Module 1 — Database & Memory Persistence Layer (`src/db/`)**
- Sub-Agent 2: **Module 2 — External Integration Services (`src/services/`)**
- Sub-Agent 3: **Module 3 — Dynamic Skills & Prompt Management (`src/agents/prompts.py`)**
- Sub-Agent 4: **Module 4 — Worker Agents (`src/agents/workers/`)**
- Sub-Agent 5: **Module 5 — Graph Orchestration & State Machine (`src/agents/`)**
- Sub-Agent 6: **Module 6 — REST API & WebSockets Layer (`src/api/` & `main.py`)**

### 4.2 Sub-Agent Execution Rules
Every sub-agent must strictly adhere to the following workflow:
1. **Scope Limit**: Implement only code, models, functions, and unit tests belonging to its assigned module.
2. **Mock Isolation**: Unit tests MUST NOT make live network calls to Groq, Supabase, Tavily, or Edge-TTS. Use `unittest.mock.patch`, `MagicMock`, and `AsyncMock` as detailed in `doc/08_detailed_design.md`.
3. **Quality Bar**:
   - `pytest tests/unit/test_<module>.py -v` MUST pass with 100% success.
   - `mypy src/<module_path>` MUST return zero type errors.
   - `ruff check src/<module_path>` MUST return zero linting/formatting errors.
4. **Completion Report**: Upon finishing, the sub-agent sends a message via `send_message` detailing implemented components, test results, and lint status.

---

## 5. Progress Tracking & Checklist Management Protocol
You (the main orchestrator agent) are required to maintain `doc/tasks/progress.md` in real time:
- As sub-agents report task completions via messages, use `replace_file_content` to check off completed items in `doc/tasks/progress.md` (`- [ ]` → `- [x]`).
- Do not mark items complete until the sub-agent explicitly verifies that pytest, mypy, and ruff checks have passed for those components.

---

## 6. Exact Sub-Agent Prompt Templates

When calling `invoke_subagent`, pass the following exact prompts to each respective sub-agent:

---

### Sub-Agent 1: Module 1 — Database & Memory Persistence Layer
```text
Role: Database & Vector Persistence Engineer
Target Workspace: src/db/, seeds/, tests/unit/test_db.py

Your objective is to implement and unit-test Module 1 of TranSafe strictly following `doc/08_detailed_design.md` Section 2 and `doc/05_database_schema.md`.

Tasks:
1. Verify environment dependencies (supabase, groq, pydantic, pytest).
2. Implement Pydantic data models `FraudCaseRecord` and `FraudMemoryRecord` in `src/db/vector_store.py` / `src/db/supabase.py`.
3. Implement `src/db/supabase.py`:
   - `init_supabase()`
   - `insert_fraud_case(case_data: dict) -> str`
   - `update_fraud_case_status(case_id: str, status: str, action_taken: str)`
   - `insert_call_transcript(case_id: str, speaker: str, utterance: str, risk_score: int) -> str`
   - `fetch_case_context(case_id: str) -> dict`
   - `fetch_telemetry_events(user_id: str, session_id: str, limit: int = 100) -> list[dict]`
   - `fetch_user_transaction_history(sender_account: str, days: int = 90) -> dict`
   - `insert_case_entities(case_id: str, entities: list) -> None`
   - `insert_phishing_submission(submission_data: dict) -> str`
   - `update_transaction_status(transaction_id: str, status: str, unfreeze_at: Optional[str] = None) -> None`
   - `insert_admin_alert(alert_data: dict) -> str`
4. Implement `src/db/vector_store.py`:
   - `init_vector_store()`
   - `embed_text(text: str) -> list[float]` (Groq nomic-embed-text-v1.5)
   - `search_fraud_memory(query: str, threshold: float = 0.75, top_k: int = 5) -> list[dict]`
   - `check_blacklist(phone: Optional[str] = None, url: Optional[str] = None) -> list[dict]`
   - `add_fraud_memory(case_id: Optional[str], fraud_type: str, content: str, metadata: dict) -> None`
5. Create mock database seed script `seeds/seed_db.py` using `faker` (ms_MY locale) to generate mock users, accounts, transactions, and vector memories.
6. Create comprehensive unit tests in `tests/unit/test_db.py`:
   - Mock `supabase.create_client` and `groq.Groq` clients.
   - Assert `embed_text` returns 768-dimensional float vector.
   - Assert `fetch_case_context` aggregates transcripts, phishing content, and entities correctly.
   - Assert `search_fraud_memory` filters results by similarity threshold.
7. Run verification commands:
   - `pytest tests/unit/test_db.py -v`
   - `mypy src/db`
   - `ruff check src/db`
8. Fix any errors until all tests and lints pass clean, then send a completion report back to the main agent.
```

---

### Sub-Agent 2: Module 2 — External Integration Services
```text
Role: Cloud Services Integration Engineer
Target Workspace: src/services/, tests/unit/test_services.py

Your objective is to implement and unit-test Module 2 of TranSafe strictly following `doc/08_detailed_design.md` Section 3 and `doc/02_architecture.md` Section 4.

Tasks:
1. Verify environment dependencies (groq, tavily-python, edge-tts, pytest, pytest-asyncio).
2. Implement `src/services/vision.py`:
   - `extract_text_from_image(base64_image: str) -> str`: Calls Groq Vision (`llama-3.2-11b-vision-preview`) to extract text from base64 screenshot data.
3. Implement `src/services/stt.py`:
   - `transcribe_audio_chunk(audio_bytes: bytes, language: str = "en") -> str`: Calls Groq Whisper (`whisper-large-v3`) for audio chunk transcription.
4. Implement `src/services/tts.py`:
   - `synthesize_text_to_audio(text: str, voice: str = "en-SG-LunaNeural") -> bytes`: Uses `edge-tts` for neural text-to-speech synthesis (supporting `en-SG-LunaNeural` and `ms-MY-YasminNeural`).
5. Implement `src/services/tavily.py`:
   - `tavily_search(entities: list[str]) -> list[dict]`: Queries Tavily Search API targeting Malaysian domains (`semak.my`, `rmp.gov.my`, `bnm.gov.my`, `lowyat.net`).
6. Create comprehensive unit tests in `tests/unit/test_services.py`:
   - Mock `Groq.chat.completions`, `Groq.audio.transcriptions`, `TavilyClient`, and `edge_tts.Communicate`.
   - Assert vision OCR extraction handles base64 image strings properly.
   - Assert STT returns transcribed text string from audio bytes input.
   - Assert TTS synthesizes non-empty audio bytes.
   - Assert Tavily search formats query and returns filtered results list.
7. Run verification commands:
   - `pytest tests/unit/test_services.py -v`
   - `mypy src/services`
   - `ruff check src/services`
8. Fix any errors until all tests and lints pass clean, then send a completion report back to the main agent.
```

---

### Sub-Agent 3: Module 3 — Dynamic Skills & Prompt Management
```text
Role: Prompt Engineer & Knowledge Manager
Target Workspace: src/agents/prompts.py, backend/skills/, tests/unit/test_skills.py

Your objective is to implement and unit-test Module 3 of TranSafe strictly following `doc/08_detailed_design.md` Section 4 and `doc/03_agent_flow.md`.

Tasks:
1. Verify environment dependencies (pytest).
2. Create external markdown skill files in `backend/skills/`:
   - `backend/skills/phone_dialogue_guide.md`: Safety & data privacy guardrails, zero user info access rules, Auto-Talk dialogue policy.
   - `backend/skills/anchor_questions.md`: Pre-set verification questions for unknown callers (e.g. AQ-1 employee ID verification).
3. Implement `src/agents/prompts.py`:
   - `load_skill_file(skill_filename: str) -> str`
   - `get_phone_dialogue_guide() -> str`
   - `get_anchor_questions() -> list[dict]`
   - `build_telemetry_prompt(user_id: str, session_id: str, device_id: str, events: list, metrics: Optional[dict] = None, biometrics: Optional[dict] = None, fingerprint: Optional[dict] = None) -> str`
   - `build_financial_prompt(pending_tx: dict, history: dict, case_context: Optional[dict]) -> str`
   - `build_research_prompt(entities: list, internal_hits: list, tavily_hits: list) -> str`
   - `build_phishing_analysis_prompt(source: str, content: str) -> str`
   - `build_phone_highlighter_prompt(text: str) -> str`
   - `build_xai_prompt(state: dict) -> str`
4. Create unit tests in `tests/unit/test_skills.py`:
   - Test loading markdown skill files and assert key header phrases exist.
   - Test anchor question JSON parsing and verify question structure.
   - Test prompt string formatting functions with sample input dictionaries and verify interpolated text.
5. Run verification commands:
   - `pytest tests/unit/test_skills.py -v`
   - `mypy src/agents/prompts.py`
   - `ruff check src/agents/prompts.py`
6. Fix any errors until all tests and lints pass clean, then send a completion report back to the main agent.
```

---

### Sub-Agent 4: Module 4 — Worker Agents
```text
Role: Multi-Agent Worker Logic Engineer
Target Workspace: src/agents/workers/, tests/unit/test_workers.py

Your objective is to implement and unit-test Module 4 of TranSafe strictly following `doc/08_detailed_design.md` Section 5 and `doc/03_agent_flow.md` Section 5.

Tasks:
1. Verify environment dependencies (pydantic, langgraph, groq, pytest).
2. Define `WorkerFinding` Pydantic model:
   - `worker: str` ("telemetry" | "research" | "financial" | "phone" | "phishing")
   - `score: int` (0–100)
   - `confidence: float` (0.0–1.0)
   - `evidence: list[str]`
   - `error: Optional[str] = None`
3. Implement worker node functions as pure state-transformation functions:
   - `src/agents/workers/telemetry.py`: `telemetry_worker_node(state: GraphState) -> dict` (analyzes flight times, tab switches, copy-paste, device orientation).
   - `src/agents/workers/financial.py`: `financial_worker_node(state: GraphState) -> dict` (analyzes 90-day baseline, amount deviations, timing, and cross-checks active `associated_case_context`).
   - `src/agents/workers/research.py`: `research_worker_node(state: GraphState) -> dict` (handles QUERY mode via pgvector + Tavily fallback, and INGEST mode for report summarization).
   - `src/agents/workers/phishing.py`: `phishing_worker_node(state: GraphState) -> dict` (extracts entities and evaluates phishing indicators for text/URL/image).
   - `src/agents/workers/phone.py`: `phone_worker_node(state: GraphState) -> dict` (Listen Mode utterance highlighter + Auto-Talk conversation state machine).
4. Create unit tests in `tests/unit/test_workers.py`:
   - Mock DB calls (`fetch_telemetry_events`, `fetch_user_transaction_history`, `search_fraud_memory`, `check_blacklist`) and LLM invocations.
   - Assert `financial_worker_node` overrides score to 95+ when `recipient_account` matches `associated_case_context`.
   - Assert `telemetry_worker_node` handles missing optional biometric blocks gracefully.
   - Assert `research_worker_node` executes Tavily fallback when internal pgvector score < 0.75.
   - Assert `phishing_worker_node` returns extracted entities in state updates.
5. Run verification commands:
   - `pytest tests/unit/test_workers.py -v`
   - `mypy src/agents/workers`
   - `ruff check src/agents/workers`
6. Fix any errors until all tests and lints pass clean, then send a completion report back to the main agent.
```

---

### Sub-Agent 5: Module 5 — Graph Orchestration & State Machine
```text
Role: LangGraph Orchestration & State Architect
Target Workspace: src/agents/ (state.py, orchestrator.py, graph_nodes.py, graph.py), tests/unit/test_graph.py

Your objective is to implement and unit-test Module 5 of TranSafe strictly following `doc/08_detailed_design.md` Section 6 and `doc/03_agent_flow.md` Sections 2, 4, 6–8.

Tasks:
1. Verify environment dependencies (langgraph, langchain-core, pytest).
2. Implement `src/agents/state.py`:
   - Define exact `GraphState` TypedDict containing all input, routing, worker output, risk assessment, XAI, phone session, action, and streaming fields.
3. Implement `src/agents/orchestrator.py`:
   - `TRIGGER_WORKER_MAP` dictionary.
   - `orchestrator_node(state: GraphState) -> dict`: Evaluates `trigger_type`, loads `associated_case_context` from DB if `associated_case_id` is present, and determines `workers_to_activate`.
4. Implement `src/agents/graph_nodes.py`:
   - `risk_scorer_node(state: GraphState) -> dict`: Calculates weighted risk score across active workers (telemetry 0.15, research 0.25, financial 0.30, phone 0.20, phishing 0.10) and assigns `risk_tier` (LOW: 0-39, MEDIUM: 40-69, HIGH: 70-100).
   - `xai_node(state: GraphState) -> dict`: Invokes LLM to produce structured bilingual (EN/MS) JSON explanation report.
   - `action_dispatcher_node(state: GraphState) -> dict`: Resolves tier action (`FREEZE_30_MIN`, `BIOMETRIC_CHALLENGE`, `APPROVE`) and updates DB records.
5. Implement `src/agents/graph.py`:
   - `compile_graph() -> CompiledStateGraph`: Constructs `StateGraph(GraphState)`, wires conditional edges for worker fan-out, join edges back to scorer, and linear evaluation path `scorer -> xai -> dispatcher -> END`.
6. Create unit tests in `tests/unit/test_graph.py`:
   - Assert `orchestrator_node` routes `TRANSACTION` trigger to `["financial", "telemetry", "research"]`.
   - Assert `risk_scorer_node` normalizes weighted scores correctly when only a subset of workers is active.
   - Assert `action_dispatcher_node` sets `FREEZE_30_MIN` action for `HIGH` risk tier.
   - Test full graph execution with mocked LLM nodes.
7. Run verification commands:
   - `pytest tests/unit/test_graph.py -v`
   - `mypy src/agents`
   - `ruff check src/agents`
8. Fix any errors until all tests and lints pass clean, then send a completion report back to the main agent.
```

---

### Sub-Agent 6: Module 6 — REST API & WebSockets Layer
```text
Role: FastAPI & Real-Time Protocol Engineer
Target Workspace: main.py, src/api/, src/models/, tests/unit/test_api.py

Your objective is to implement and unit-test Module 6 of TranSafe strictly following `doc/08_detailed_design.md` Section 7 and `doc/04_api_design.md`.

Tasks:
1. Verify environment dependencies (fastapi, uvicorn, httpx, pydantic, pytest).
2. Implement Pydantic schemas in `src/models/schemas.py`:
   - Request and response models for telemetry, transaction, call, phishing, report, biometric result, takeover, and recent cases endpoints.
3. Implement `src/api/triggers.py`:
   - `POST /api/v1/trigger/telemetry`
   - `POST /api/v1/trigger/transaction`
   - `POST /api/v1/trigger/call`
   - `POST /api/v1/trigger/phishing`
   - `POST /api/v1/trigger/report`
   - `POST /api/v1/biometric/result`
   - `POST /api/v1/call/{session_id}/takeover`
   - `GET /api/v1/cases/recent`
4. Implement `src/api/websocket.py`:
   - WebSocket `/ws/session/{session_id}` handler streaming pipeline status messages and final `result` payload.
5. Implement `src/api/websocket_call.py`:
   - WebRTC audio stream handler `/ws/call/{call_session_id}/audio` (binary Opus/WebM streaming to STT).
   - Real-time events stream handler `/ws/call/{call_session_id}/events` (streaming pre-checks and live highlight spans).
6. Implement `src/api/admin.py`:
   - Admin REST endpoints `/admin/v1/cases`, `/admin/v1/accounts/{account}/freeze`, `/admin/v1/accounts/{account}/unfreeze`, `/admin/v1/analytics/summary`.
7. Implement `main.py`:
   - Application lifespan, CORS middleware, API key header verification (`verify_api_key`), router mounting, health check endpoint `GET /health`, and pre-compiling LangGraph instance on startup.
8. Create integration and unit tests in `tests/unit/test_api.py`:
   - Use FastAPI `TestClient`.
   - Assert `401 Unauthorized` when `X-API-Key` is missing or invalid.
   - Assert `202 Accepted` and valid `session_id` on transaction trigger.
   - Assert `GET /api/v1/cases/recent` returns user case history.
   - Test WebSocket streaming handlers with mock state updates.
9. Run verification commands:
   - `pytest tests/unit/test_api.py -v`
   - `mypy main.py src/api`
   - `ruff check main.py src/api`
10. Fix any errors until all tests and lints pass clean, then send a completion report back to the main agent.
```

---

## 7. Master Quality Assurance & Full-Suite Verification Protocol

Once all 6 sub-agents have completed their tasks and reported back, you (the main orchestrator agent) must execute the final master quality assurance pass across the entire codebase:

### 7.1 Complete Test Suite Execution
Execute the entire unit test suite from the project root:
```bash
pytest tests/unit/ -v --tb=short
```
*Requirement*: All unit tests across `test_db.py`, `test_services.py`, `test_skills.py`, `test_workers.py`, `test_graph.py`, and `test_api.py` MUST pass with 0 failures and 0 errors.

### 7.2 Strict Static Type Checking
Run `mypy` across the entire codebase:
```bash
mypy src main.py
```
*Requirement*: Must return `Success: no issues found in X source files`.

### 7.3 Code Format & Lint Compliance
Run `ruff` across the codebase:
```bash
ruff check src main.py tests
```
*Requirement*: Must return zero errors or warnings.

### 7.4 Final Progress Checklist Finalization
Verify that `doc/tasks/progress.md` has all tasks checked off (`[x]`). If any items remain unchecked, resolve them immediately.

Once all verification steps pass clean, summarize the overall build status and confirm project completion to the user!
