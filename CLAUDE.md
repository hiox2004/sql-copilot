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
- Secrets live in `.env` (gitignored); `.env.example` is the template.

## Success criteria (v1, agreed 2026-11-05; revise after first baseline)
- >= 70% execution accuracy on held-out query templates (a guess; adjust once a baseline exists).
- 100% of write/injection attempts in the red-team set blocked.
- p95 latency < 10 s on the user's laptop.
- Every golden query verified by execution.

## Commands
- Start DB: `docker compose -f infra/docker-compose.yml --env-file .env up -d`
- Stop DB: `docker compose -f infra/docker-compose.yml down` (add `-v` to wipe data)
- Activate venv: `.\.venv\Scripts\Activate.ps1`

## Working style
Teach first, then build, then recap. Keep chat compact; put depth in the study guide.
