# Module 4: Worker Agents Tasks (`src/agents/workers/`)

- [ ] Define `WorkerFinding` Pydantic models.
- [ ] Implement `telemetry_worker_node` logic (detecting anomalies in flight times, tab switches, device fingerprint).
- [ ] Implement `financial_worker_node` logic (anomalous patterns, amounts, timing, cross-checking active case context).
- [ ] Implement `research_worker_node` logic (QUERY mode: pgvector + Tavily fallback; INGEST mode: fraud report summarisation).
- [ ] Implement `phishing_worker_node` logic (entity extraction, deep content analysis).
- [ ] Implement `phone_worker_node` real-time highlighter (Listen Mode — keyword fast pass + LLM span detection).
- [ ] Implement `phone_worker_node` dialogue controller (Auto-Talk Mode — conversation state machine).
- [ ] Write unit tests for each worker node function (`tests/unit/test_workers.py`).
