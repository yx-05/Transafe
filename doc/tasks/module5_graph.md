# Module 5: Graph Orchestration & State Machine Tasks (`src/agents/`)

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
