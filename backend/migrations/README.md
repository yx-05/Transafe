# TranSafe — Database Migrations

Migrations are applied by hand through the **Supabase SQL Editor**. There is no
migration runner and no version table; each file is written to be idempotent so
that "did someone already run this?" is never a question you have to answer.

| File | What it does | Applies to |
| --- | --- | --- |
| `../schema.sql` | v1 baseline schema (users, accounts, transactions, fraud_cases, call_transcripts, …) | v1 |
| `003_adaptive_case_labeling.sql` | v1 adaptive labelling + `learned_keywords` | v1 |
| `v2_enterprise.sql` | **v2 enterprise layer** — 13 new tables, 2 vector indexes, 1 RPC | v2 |

---

## Applying `v2_enterprise.sql`

### Prerequisite: the `vector` extension (pgvector)

`case_mo.embedding` and `campaigns.mo_embedding` are `VECTOR(768)` columns, so
pgvector must be available before the tables can be created.

On Supabase this is usually already enabled (v1 uses vector columns too). The
migration begins with:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- for gen_random_uuid()
```

so in the normal case you do not need to do anything. To confirm ahead of time:

```sql
SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pgcrypto');
```

If `vector` is missing, enable it via **Dashboard → Database → Extensions →
search "vector" → Enable**, or run `CREATE EXTENSION IF NOT EXISTS vector;`
yourself. Do this *before* running the migration — the `CREATE TABLE`
statements will fail with `type "vector" does not exist` otherwise.

> **768 dimensions, not 1024.** Every vector column in v2 is `VECTOR(768)` to
> match DashScope `text-embedding-v3` as already used by
> `backend/src/db/vector_store.py::embed_text()`. Do not change the dimension
> without changing that function — a mismatch surfaces as a runtime insert error,
> not a migration error.

### Steps

1. Open **Supabase Dashboard → SQL Editor → New Query**.
2. Paste the **entire contents** of `v2_enterprise.sql`. Do not run it in
   fragments — later statements reference earlier tables (e.g. `campaign_cases`
   references `campaigns`, and the `graph_neighbours` RPC references
   `case_entity_links`).
3. Click **Run**. Expect `Success. No rows returned`.
4. Run the verification queries below.

The migration touches **new tables only**. It contains no `ALTER TABLE`, no
`DROP`, and no `INSERT`, so it cannot modify or delete v1 data. It does add
foreign keys *into* v1 (`fraud_cases.id`), which means `fraud_cases` must
already exist — i.e. run `schema.sql` first on a fresh project.

---

## Verification

### 1. All 13 tables exist

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'ns_events', 'entities', 'case_entity_links', 'case_mo',
    'case_discovery_state', 'case_links', 'campaigns', 'campaign_cases',
    'artifacts', 'artifact_consumption', 'mcp_access_log',
    'eval_runs', 'eval_results'
  )
ORDER BY table_name;
```

Expect **13 rows**. Anything less means the script was truncated on paste — the
SQL Editor has a size limit; re-paste and re-run (safe, see idempotency below).

### 2. The `graph_neighbours` RPC exists with the right signature

This is the one object that is *not* a table, and the one most likely to be
missed. `PostgresGraphStore.neighbours()` calls it via
`client.rpc("graph_neighbours", {"entity_id": ..., "depth": ...})`.

```sql
SELECT p.proname,
       pg_get_function_arguments(p.oid)    AS args,
       pg_get_function_result(p.oid)       AS returns
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname = 'graph_neighbours';
```

Expect exactly one row:

- `args` → `entity_id uuid, depth integer DEFAULT 1`
- `returns` → `TABLE(id uuid, entity_type text, value_norm text, value_raw text, case_count integer)`

Then smoke-test that it is actually callable (returns 0 rows on an empty DB,
which is a pass — you are testing that it resolves, not that it finds anything):

```sql
SELECT * FROM public.graph_neighbours('00000000-0000-0000-0000-000000000000'::uuid, 1);
```

If this errors with `function public.graph_neighbours(uuid, integer) does not
exist`, the RPC did not get created. Re-run the `CREATE OR REPLACE FUNCTION`
block at the bottom of the migration on its own.

> Supabase caches the PostgREST schema. A brand-new RPC can 404 from the REST
> API for a few seconds even though it exists in the database. If
> `GET /enterprise/graph` reports no neighbours immediately after migrating,
> wait ~30s, or force a reload with `NOTIFY pgrst, 'reload schema';`.

### 3. Vector columns are 768-dim

```sql
SELECT c.relname AS table_name,
       a.attname AS column_name,
       format_type(a.atttypid, a.atttypmod) AS type
FROM pg_attribute a
JOIN pg_class     c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND a.attname IN ('embedding', 'mo_embedding')
  AND NOT a.attisdropped;
```

Expect `vector(768)` for both `case_mo.embedding` and `campaigns.mo_embedding`.

### 4. End-to-end check from the app

With the backend running (`cd backend && uv run uvicorn main:app --reload`):

```bash
curl -s localhost:8000/enterprise/overview | head -40
```

The v2 read endpoints are deliberately failure-tolerant per table: before the
migration they render zeros and empty lists instead of a 500. So a `200` alone
does **not** prove the migration worked — use the SQL checks above for that.
What the endpoint does prove is that nothing is erroring after the fact.

---

## Is re-running safe? — Yes, explicitly

**Re-running `v2_enterprise.sql` on a database that already has v2 tables and
live data is safe and non-destructive. No rows are added, changed or removed.**

Every statement in the file is one of:

| Construct | Behaviour on re-run |
| --- | --- |
| `CREATE EXTENSION IF NOT EXISTS` | no-op |
| `CREATE TABLE IF NOT EXISTS` | no-op — **existing table and all its rows are left completely untouched** |
| `CREATE INDEX IF NOT EXISTS` | no-op |
| `CREATE OR REPLACE FUNCTION` | function body is redefined; no data involved |

There are no `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `DROP` or `ALTER`
statements, so there is no path by which a re-run can lose data. Partial
application is also fine: if the first run failed halfway (bad paste, timeout),
just run the whole file again — the objects that already exist are skipped and
the missing ones get created.

### Two caveats for whoever edits this migration later

1. **`CREATE TABLE IF NOT EXISTS` does not upgrade an existing table.** If you
   change a column, constraint or CHECK list in this file, re-running it against
   a database where that table already exists will silently do *nothing* — the
   table keeps its old shape and you get no error. Schema *changes* must ship as
   a new, separate migration file using explicit
   `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` / `DROP CONSTRAINT IF EXISTS` +
   `ADD CONSTRAINT`, exactly as `003_adaptive_case_labeling.sql` does. Never
   "fix" a table by editing this file.
2. **`CREATE OR REPLACE FUNCTION` cannot change a function's return type.** If
   you ever alter the columns `graph_neighbours` returns, Postgres will reject
   the replace with `cannot change return type of existing function`. In that
   case drop it first:
   ```sql
   DROP FUNCTION IF EXISTS public.graph_neighbours(UUID, INT);
   ```
   Adding or reordering *parameters* creates an overload rather than replacing
   the original, which will make the PostgREST call ambiguous — drop the old
   signature in that case too.

### About the ivfflat vector indexes

`idx_case_mo_embedding` and `idx_campaigns_mo_embedding` are `ivfflat ... WITH
(lists = 100)`. They are created last, and creating them on empty tables is
valid but produces poorly-calibrated centroids. This does not affect
correctness — pgvector still returns exact-enough results at this scale, and
novelty checks in `clustering.py` compute cosine in Python over a small
candidate set rather than relying on the index. If the dataset ever grows past
a few thousand rows and similarity queries get slow, rebuild them:

```sql
REINDEX INDEX CONCURRENTLY public.idx_case_mo_embedding;
REINDEX INDEX CONCURRENTLY public.idx_campaigns_mo_embedding;
```

---

## Rollback

There is no automated rollback. v2 is purely additive, so the way to "undo" it
is to drop the new objects — this destroys v2 data only and leaves v1 fully
intact:

```sql
DROP FUNCTION IF EXISTS public.graph_neighbours(UUID, INT);
DROP TABLE IF EXISTS public.eval_results, public.eval_runs,
                     public.mcp_access_log, public.ns_events,
                     public.artifact_consumption, public.artifacts,
                     public.campaign_cases, public.campaigns,
                     public.case_links, public.case_discovery_state,
                     public.case_mo, public.case_entity_links,
                     public.entities
CASCADE;
```

Order matters only because of foreign keys; `CASCADE` handles it. Do not add v1
tables to this list.
