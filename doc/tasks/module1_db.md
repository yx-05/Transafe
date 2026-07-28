# Module 1: Database & Memory Persistence Layer Tasks (`src/db/`)

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
