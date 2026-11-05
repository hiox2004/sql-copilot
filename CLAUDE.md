# SQL Copilot

Schema-grounded Text-to-SQL copilot: plain-English question -> safe PostgreSQL query. Built as a **learning project**: the `tutor` agent (default, see `.claude/settings.json`) explains each piece while building it. Study material: `docs/study-guide.html`.

## Pipeline
Question -> **Retrieve** (hybrid dense+BM25, data dictionary, FK graph walk) -> **Generate** (Qwen2.5-Coder 1.5B/3B + QLoRA adapter, JSON out: `sql`, `tables_used`, `assumptions`) -> **Verify** (LangGraph loop: EXPLAIN, patch with error, max 2 retries) -> **Guard** (read-only role, sqlglot SELECT-only, timeout, LIMIT) -> results + assumptions.

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
- Secrets live in `.env` (gitignored); `.env.example` is the template.

## Commands
- Start DB: `docker compose -f infra/docker-compose.yml --env-file .env up -d`
- Stop DB: `docker compose -f infra/docker-compose.yml down` (add `-v` to wipe data)
- Activate venv: `.\.venv\Scripts\Activate.ps1`

## Working style
Teach first, then build, then recap. Keep chat compact; put depth in the study guide.
