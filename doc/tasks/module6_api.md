# Module 6: REST API & WebSockets Layer Tasks (`src/api/` & `main.py`)

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
