# Module 3: Dynamic Skills & Prompt Management Tasks (`src/agents/prompts.py`)

- [ ] Implement `load_skill_file` to read markdown skill definitions from `backend/skills/`.
- [ ] Implement `get_phone_dialogue_guide` for Phone Worker Auto-Talk mode.
- [ ] Implement `get_anchor_questions` parsing logic.
- [ ] Build prompt formatting for `telemetry_worker` (handling session metrics, biometrics, network fingerprint).
- [ ] Build prompt formatting for `financial_worker` (handling pending tx, 90-day baseline, case context overrides).
- [ ] Build prompt formatting for `research_worker` (handling QUERY mode and INGEST mode).
- [ ] Build prompt formatting for `phishing_worker` (handling TEXT, URL, IMAGE sources).
- [ ] Build prompt formatting for `phone_worker` real-time utterance highlighter (LISTEN mode).
- [ ] Write unit tests for prompt parsing and generation (`tests/unit/test_skills.py`).
