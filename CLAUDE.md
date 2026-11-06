# SQL Copilot

Schema-grounded Text-to-SQL copilot: plain-English question -> safe PostgreSQL query. Built as a **learning project**: the `tutor` agent (default, see `.claude/settings.json`) explains each piece while building it. Study material: `docs/study-guide.html`.

## Pipeline
Question -> **Retrieve** (hybrid dense+BM25, data dictionary, FK graph walk) -> **Generate** (small open model, primary Qwen2.5-Coder-1.5B-Instruct, challenger Qwen3-4B-Instruct-2507 (non-thinking), Qwen3.5-4B parked; chosen by eval bake-off; QLoRA adapter, JSON out: `sql`, `tables_used`, `assumptions`) -> **Verify** (LangGraph loop: EXPLAIN, patch with error, max 2 retries) -> **Guard** (read-only role, sqlglot SELECT-only, timeout, LIMIT) -> results + assumptions.

## Layout
- `src/t2sql/{core,retrieval,generation,validation,graph,dialects}` - pure Python package, knows nothing about FastAPI
- `api/` FastAPI | `app/` Streamlit (only calls the API)
- `data/` schema, dictionaries, profiles, eval set | `training/` QLoRA + data gen (heavy deps stay here)
- `eval/` metrics | `infra/` docker | `tests/` | `docs/`

## Conventions
- Python 3.12, venv at `.venv`. Dependency direction: app -> api -> graph -> retrieval/generation/validation.
- One prompt builder shared by training, eval and production.
- No dialect names (e.g. "postgres") outside `src/t2sql/dialects/` and `data/`.
- Every dialect implements the `Dialect` Protocol; each DB has a YAML profile in `data/profiles/`.
- Eval scores compare result rows, not SQL text. Split train/test by query template.
- Never run `EXPLAIN ANALYZE`. Never index row data or personal data.
- Model serving: llama.cpp `llama-server` with a GGUF file, run natively on Windows (4 GB VRAM). Talk to it only through the OpenAI-compatible HTTP API (base URL from config) so the engine stays swappable. Train on Colab/Kaggle; evaluate the quantized GGUF actually served.
- Dictionary YAML (`data/dictionaries/<db>.yaml`) is parsed by `t2sql.retrieval.dictionary.load_dictionary` into the models in `t2sql.core.dictionary_models` (unknown fields rejected, frozen, strict strings, descriptions <= 200 chars). Metric `sql` is one complete SELECT using only `{today}` and its declared `{parameters}`. Quote YAML words like "on"/"off"/"yes"/"no". PII columns are flagged `pii: true`.
- Pinned "today" = 2026-11-05 12:00 UTC (`REF_NOW` in `infra/postgres/init/02_load_schema.sh`). Never use `NOW()` in seed/check SQL (use `pg_temp.ref()`); the prompt must tell the model the same date.
- Database = 36 tables (`data/schema/`): files load in name order and `99_checks.sql` aborts init on inconsistent data. Add a check whenever you add a rule. Run on demand: `MSYS_NO_PATHCONV=1 docker exec t2sql-postgres psql -U admin -d saas -v ref_now="'2026-11-05 12:00:00+00'" -f /schema/99_checks.sql` (Git Bash mangles `/schema` without the env var).
- Secrets live in `.env` (gitignored); `.env.example` is the template.

## Business definitions (agreed 2026-11-05; these go into the data dictionary)
- Customer = organization. MRR = sum of `subscriptions.mrr_cents` where status IN ('active','past_due'); trialing and canceled excluded. past_due counts toward MRR but is not an "active customer".
- Big account = enterprise plan. Revenue = `payments.amount_cents` where status = 'succeeded', orders and invoices both, in dollars (cents / 100.0).
- Churned = status 'canceled' with `canceled_at` in the window (default last 30 days). Active user = successful login in the last 7 days.
- "This month" = calendar month of the pinned date, UTC (show it in `assumptions`). Open tickets = status IN ('open','pending').
- Known seed weakness to fix later: logins are uniform (99% of users active in 30 days).

## Training strategy
Decision (2026-11-05): **A (schema-specific) now, B (schema-agnostic skills + held-out schema) later.** Still write the training-data generator against an introspected schema, not hard-coded to ours, so B stays cheap. Remember the memorization risk when reading eval scores.

## Success criteria (v1, agreed 2026-11-05; revise after first baseline)
- >= 70% execution accuracy on held-out query templates (a guess; adjust once a baseline exists).
- 100% of write/injection attempts in the red-team set blocked.
- p95 latency < 10 s on the user's laptop.
- Every golden query verified by execution.

## Commands
- Start DB: `docker compose -f infra/docker-compose.yml --env-file .env up -d`
- Stop DB: `docker compose -f infra/docker-compose.yml down` (add `-v` to wipe data)
- Snapshot DB to file: `bash infra/scripts/dump_db.sh` -> `data/snapshots/saas.sql` (gitignored; seed files in `data/schema/` are the source of truth)
- Scratch copy for experiments: `bash infra/scripts/restore_db.sh` -> database `saas_scratch` (re-run to reset; refuses to touch `saas`)
- Browse DB (pgAdmin): `docker compose -f infra/docker-compose.yml --env-file .env --profile tools up -d pgadmin`, open http://localhost:5050
- Tests / lint (venv active): `pytest`, `pytest tests/unit`, `pytest -m integration` (needs DB up), `ruff check .`
- Activate venv: `.\.venv\Scripts\Activate.ps1`

## Docs upkeep
- Every new tool, service, env var, port or setup step goes into `docs/setup.md` in the same turn (update its status table and "Last updated").
- Every new concept or build step goes into `docs/study-guide.html`.

## Working style
Teach first, then build, then recap. Keep chat compact; put depth in the study guide.
