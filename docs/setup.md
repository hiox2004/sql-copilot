# Setup guide

Everything needed to get this project running on a fresh Windows machine, and how each piece works.
**This file is a living document:** every new setup step (tools, services, environments) is appended here when it is introduced.

Last updated: 2026-11-06.

## Status at a glance

| Piece | Status | Section |
|---|---|---|
| Git repo (public, MIT) | Done | [Repository](#repository) |
| Python 3.12 virtual environment + `t2sql` package (editable) | Done | [Python](#python-environment) |
| Postgres 16 in Docker (36 tables, seeded) | Done | [Docker](#docker-compose) |
| pgAdmin (database browser) | Done, optional | [pgAdmin](#pgadmin-optional-database-browser) |
| Snapshots and scratch database | Done | [Snapshots](#snapshots-and-the-scratch-database) |
| Claude Code tutor agent + `teach` skill | Done | [Claude Code](#claude-code) |
| `pyproject.toml`, pytest, ruff, VS Code interpreter setting | Done (204 tests passing) | [Python](#python-environment) |
| Guard (`validation/guard.py`) and executor (`validation/executor.py`) | Done, tested against the red-team set | (library code, no setup) |
| GitHub Actions CI (`.github/workflows/ci.yml`) | Done: first green run 2026-11-06 (34 s) | [CI](#continuous-integration-ci) |
| Draft dictionary generator (`scripts/draft_dictionary.py`) | Done | [Draft dictionary](#draft-dictionary-generator) |
| llama.cpp + Qwen2.5-Coder-1.5B GGUF (local model serving) | Downloaded by script, pinned and checksum-verified | [Local model serving](#local-model-serving-llamacpp) |
| Colab/Kaggle (training) | Planned | [Planned](#planned-setups-not-done-yet) |

## Prerequisites

| Tool | Used for | Check |
|---|---|---|
| Windows 11 | Host OS (project developed here) | |
| Python 3.12 | Package code, venv | `python --version` |
| Docker Desktop (running) | Postgres, pgAdmin | `docker --version`, `docker compose version` |
| Git + GitHub CLI (`gh`) | Version control, repo creation | `git --version`, `gh auth status` |
| Git Bash (ships with Git) | Running the `.sh` helper scripts | |

Hardware this was planned around: Ryzen 5 5600H, 15.4 GB RAM, RTX 3050 Laptop with 4 GB VRAM. Docker Desktop must be **started** before any `docker` command works (otherwise: "failed to connect to the docker API").

## Repository

```
git clone https://github.com/hiox2004/sql-copilot.git
cd sql-copilot
```

`.gitattributes` forces LF line endings for `*.sh`. Without it, Windows checkouts convert them to CRLF and the scripts fail inside Linux containers.

## Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install --upgrade pip
```

Install the project and its dev tools (editable, so code changes take effect immediately):

```
pip install -e ".[dev]"
```

Everything is defined in [`pyproject.toml`](../pyproject.toml):

| Group | Packages | Why |
|---|---|---|
| Runtime | `pydantic`, `pyyaml`, `psycopg[binary]`, `python-dotenv` | Data models, YAML dictionary, Postgres driver, `.env` loading |
| Dev (`[dev]`) | `pytest`, `ruff` | Tests and lint/format checks |
| Not here on purpose | `trl`, `peft`, `bitsandbytes`, ML libraries | Heavy; they live with the training notebooks, not the API image |

Daily commands (venv activated):

| Goal | Command |
|---|---|
| Run all tests | `pytest` |
| Only fast unit tests | `pytest tests/unit` |
| Only database tests | `pytest -m integration` (auto-skipped if the DB is down) |
| Lint | `ruff check .` |
| Auto-fix lint / sort imports | `ruff check . --fix` |

Integration tests connect as the **read-only** role using values from `.env`, so start Docker first. `setuptools>=77` is required because the license is declared as the SPDX string `MIT` (the older table form is deprecated).

## Environment variables (`.env`)

```
copy .env.example .env      # PowerShell;  cp .env.example .env  in Git Bash
```

Then edit the passwords. `.env` is gitignored; `.env.example` is the committed template.

| Variable | Meaning |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Main database and its admin account |
| `POSTGRES_PORT` | Host port for Postgres (default 5432) |
| `COPILOT_RO_USER`, `COPILOT_RO_PASSWORD` | The **read-only** role the copilot uses at run time |
| `PGADMIN_EMAIL`, `PGADMIN_PASSWORD` | Only used by the optional pgAdmin container |

Optional overrides (all have defaults; read by `t2sql.core.config.Settings`):

| Variable | Default | Meaning |
|---|---|---|
| `REF_NOW` | `2026-11-05 12:00:00+00` | The pinned "today". Must include a timezone. Also read by the DB loader script; a unit test keeps the two defaults equal |
| `DB_HOST` | `127.0.0.1` | Database host. Do not use `localhost` on Windows: it tries IPv6 first and hangs |
| `LLM_BASE_URL` | `http://localhost:8080/v1` | OpenAI-compatible model server (llama.cpp, later) |

## Docker Compose

All services are defined in [`infra/docker-compose.yml`](../infra/docker-compose.yml). **Always run compose from the repo root** and pass the env file:

```
docker compose -f infra/docker-compose.yml --env-file .env <command>
```

### Services

| Service | Image | Container | Host port | Starts by default? |
|---|---|---|---|---|
| `postgres` | `postgres:16` | `t2sql-postgres` | `127.0.0.1:5432` | Yes |
| `pgadmin` | `dpage/pgadmin4:latest` (floating tag) | `t2sql-pgadmin` | `127.0.0.1:5050` | No (profile `tools`) |

Both ports are bound to `127.0.0.1`, so they are reachable only from this machine, not from your network.

### How the `postgres` service is wired

| Piece | What it does |
|---|---|
| `environment: POSTGRES_*` | The official image creates the database and admin user on first start |
| `environment: COPILOT_RO_*` | Passed through so the init script can create the read-only role |
| volume `pgdata` | Named Docker volume holding the data files; survives stop/restart/`down` |
| mount `./postgres/init` -> `/docker-entrypoint-initdb.d` | Init scripts, run **once**, in name order, only when the data volume is **empty** |
| mount `../data/schema` -> `/schema` | The schema, seed and check SQL files, read-only |
| `healthcheck: pg_isready` | Reports "healthy" when Postgres accepts connections; `pgadmin` waits for it |

### What happens on first start (empty volume)

1. `01_roles.sh` creates the read-only role `copilot_ro` (`default_transaction_read_only = on`, `statement_timeout = 10s`).
2. `02_load_schema.sh` runs every `/schema/*.sql` file in name order, passing the pinned date as a psql variable:
   `01_schema.sql` -> `02_schema_extra.sql` -> `03_seed_core.sql` -> `04_seed_extra.sql` -> `99_checks.sql`.
3. `99_checks.sql` runs 36 consistency queries. **If any rule is violated it raises an error and the whole initialisation fails** (the container will not become healthy).
4. The loader grants `SELECT` on all tables to `copilot_ro`.

`ref_include.inc` (not a `.sql` file, so the loader skips it) defines `pg_temp.ref()`, the pinned "now". Seed and check SQL must use it instead of `NOW()`.

### Everyday commands

| Goal | Command |
|---|---|
| Start Postgres | `docker compose -f infra/docker-compose.yml --env-file .env up -d` |
| Is it healthy? | `docker ps` |
| Open a SQL shell | `docker exec -it t2sql-postgres psql -U admin -d saas` |
| Read-only shell (as the copilot) | `docker exec -it -e PGPASSWORD=<COPILOT_RO_PASSWORD> t2sql-postgres psql -h localhost -U copilot_ro -d saas` |
| View logs | `docker compose -f infra/docker-compose.yml logs postgres` |
| Stop, keep data | `docker compose -f infra/docker-compose.yml down` |
| Stop and **delete all data** | `docker compose -f infra/docker-compose.yml down -v` |
| Rebuild from scratch | `down -v`, then `up -d` (takes under a minute) |
| Run data checks on demand | `MSYS_NO_PATHCONV=1 docker exec t2sql-postgres psql -U admin -d saas -v ref_now="'2026-11-05 12:00:00+00'" -f /schema/99_checks.sql` |

### pgAdmin (optional database browser)

```
docker compose -f infra/docker-compose.yml --env-file .env --profile tools up -d pgadmin
```

Open <http://localhost:5050>. It runs in desktop mode (no login screen). The server entry comes from `infra/pgadmin/servers.json`; the first connection asks for the `POSTGRES_USER` password from `.env`. Stop it with `... --profile tools stop pgadmin`. Its settings live in the `pgadmindata` volume.

## Snapshots and the scratch database

Three ways the data is "saved": the seed files in git are the recipe (source of truth); `data/snapshots/saas.sql` is a plain-SQL snapshot; `saas_scratch` is a disposable copy.

| Goal | Command (Git Bash, repo root) |
|---|---|
| Write a snapshot | `bash infra/scripts/dump_db.sh` -> `data/snapshots/saas.sql` (gitignored) |
| Create / reset the scratch DB | `bash infra/scripts/restore_db.sh` -> database `saas_scratch` |
| Restore another snapshot | `bash infra/scripts/restore_db.sh data/snapshots/other.sql my_db` |

`restore_db.sh` refuses to overwrite the main database. Experiment (INSERT/UPDATE/DELETE, broken queries) only in `saas_scratch`; the copilot itself only uses the read-only role on `saas`.

## Continuous integration (CI)

`.github/workflows/ci.yml` runs on every push to `main` and every pull request: install the package, `ruff check .`, start the same Docker Compose database used locally (`cp .env.example .env`, `up -d --wait`, which also runs the consistency checks), then `pytest` (unit and database-backed integration tests). Status: **verified**: the first run on 2026-11-06 passed lint, the database build and all tests in 34 seconds. If a run fails, the last step prints the database log. GitHub warns that Node 20 actions (`checkout@v4`, `setup-python@v5`) are deprecated; bump the versions when newer ones are confirmed.

## Swapping in a rebuilt database without losing the old one

When seed files change, you can test the new data first without touching the real database (this is how the login seed was fixed on 2026-11-06):

```
docker exec t2sql-postgres psql -U admin -d postgres -c "CREATE DATABASE saas_fix"
# load each file: psql -d saas_fix -v ref_now="'2026-11-05 12:00:00+00'" -f /schema/<file>.sql   (prefix with MSYS_NO_PATHCONV=1 in Git Bash)
# when happy (no open connections): ALTER DATABASE saas RENAME TO saas_old; ALTER DATABASE saas_fix RENAME TO saas;
docker exec t2sql-postgres psql -U admin -d saas -c "GRANT SELECT ON ALL TABLES IN SCHEMA public TO copilot_ro"
```

`saas_old` is the previous version; drop it (`DROP DATABASE saas_old`) once you are sure. A fresh volume (`down -v`, `up -d`) always builds the current seed files.

## Local model serving (llama.cpp)

The copilot talks to a local model server over an OpenAI-compatible HTTP API (`LLM_BASE_URL`, default `http://localhost:8080/v1`). Two scripts manage it; nothing is installed system-wide.

```
bash scripts/setup_llama.sh     # once: download + verify + extract (about 1.8 GB)
bash scripts/start_llama.sh     # run the server on 127.0.0.1:8080 (Ctrl+C to stop)
```

### Exactly what is downloaded, and from where

| File | Size | Source | SHA-256 (verified by the script) |
|---|---|---|---|
| `llama-b12175-bin-win-cuda-12.4-x64.zip` (llama.cpp build b12175, Windows x64, CUDA 12.4) | 289 MB | `github.com/ggml-org/llama.cpp/releases/download/b12175/` | `cc6d557c...c39c0985` |
| `cudart-llama-bin-win-cuda-12.4-x64.zip` (CUDA 12.4 runtime DLLs) | 391 MB | same release | `8c79a9b2...e32ae1d6` |
| `qwen2.5-coder-1.5b-instruct-q4_k_m.gguf` (the model, 4-bit) | 1.1 GB | `huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF`, pinned to commit `f86cb2c1...` | `cc324af0...933bb046` |

Full hashes are in `scripts/setup_llama.sh`. Licence of the model: Apache-2.0 (not gated, checked 2026-11-06). llama.cpp is MIT. Note: llama.cpp "releases" are automated nightly builds (all marked pre-release), so the build is pinned by tag.

### Where it lands (all gitignored, never committed)

| Path | Content |
|---|---|
| `tools/downloads/` | The two zip files, kept so re-runs need no re-download |
| `tools/llama.cpp/b12175/` | Extracted binaries (`llama-server.exe`, ...) plus the CUDA DLLs next to them |
| `models/qwen2.5-coder-1.5b-instruct/` | The GGUF model file |

### Why these choices
- **CUDA 12.4 build:** the NVIDIA driver here (580.x) supports CUDA 13.0, and a 12.4 build runs on it. The 13.5 build might need a newer driver, so it is avoided.
- **Q4_K_M:** the usual balance of size and quality; 1.1 GB leaves plenty of the 4 GB VRAM for the context.
- **Fallback:** if the GPU build misbehaves, the Vulkan build (`llama-b12175-bin-win-vulkan-x64.zip`, 38 MB, no CUDA runtime needed) works on NVIDIA too; swap the zip name and hash in the script.
- **Verification:** every download is checked against a pinned SHA-256 and deleted on mismatch; extraction is repeated whenever its stamp file (`tools/llama.cpp/b12175/.extracted-from`) is missing or differs. The hashes come from GitHub's and Hugging Face's own metadata recorded on 2026-11-06 (trust on first download, not an independent signature), and the extracted executable is not re-hashed at start-up. The server binds to `127.0.0.1` only.
- **Re-running** the setup script is safe: valid files are skipped.

### Measuring the model (baseline)

With the database up and the server running: `python scripts/run_baseline.py --mode all` (whole schema in the prompt) and `--mode oracle` (only the tables each golden answer needs, i.e. what perfect retrieval would give). Results go to `eval/results/`. The prompt also contains the dictionary's reference SQL for metrics, as production will, so metric-style questions are partly answered in the prompt; read scores with that in mind.

## Draft dictionary generator

Reads the live database structure (as the read-only role; no rows) and writes a draft dictionary for a person to complete. Needs the database running and `pip install -e ".[dev]"` done (this adds `sqlglot`).

```
python scripts/draft_dictionary.py saas      # -> data/dictionaries/saas.draft.yaml
```

The profile `data/profiles/saas.yaml` says which dialect and schema to read. `*.draft.yaml` is gitignored (regenerate any time); the finished `saas.yaml` is what gets committed. Pipe-free and safe to re-run: it only overwrites the draft file.

## Claude Code

| File | Role |
|---|---|
| `CLAUDE.md` | Project memory loaded every session: pipeline, layout, conventions, commands |
| `.claude/settings.json` | `"agent": "tutor"`: default agent for new sessions (restart Claude Code in this folder to apply) |
| `.claude/agents/tutor.md` | Teaching-first agent: explain, build, recap, check question |
| `.claude/skills/teach/SKILL.md` | Lesson format and rules for extending the study guide; invoke with `/teach` |

Study material: open `docs/study-guide.html` in a browser (single self-contained file).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `failed to connect to the docker API` | Docker Desktop is not running. Start it and retry |
| Init script changes have no effect | Init scripts run only on an empty volume. `down -v` then `up -d` |
| Container never becomes healthy | Likely a failed consistency check or SQL error: `docker logs t2sql-postgres` |
| `psql: ... C:/Program Files/Git/schema/...: No such file` | Git Bash rewrites `/schema/...` paths. Prefix the command with `MSYS_NO_PATHCONV=1` |
| `.sh` script fails with `\r: command not found` | CRLF line endings. Run `sed -i 's/\r$//' <file>`; `.gitattributes` prevents it for new checkouts |
| Port 5432 or 5050 already in use | Change `POSTGRES_PORT` in `.env`, or stop the other program |
| VS Code shows "Unresolved import: yaml / pydantic" though tests pass | The editor is using a different Python. `.vscode/settings.json` points it at `.venv`; if it still shows, press Ctrl+Shift+P, "Python: Select Interpreter", choose `.venv`, then "Developer: Reload Window" |
| A Python script that connects to the DB hangs for a long time | Host was `localhost` (IPv6 first). Use `127.0.0.1` (the default in `Settings`) |
| Windows blocks `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

## Planned setups (not done yet)

These are decided but not installed. Each gets a full section above when it is done.

- **Colab / Kaggle** notebooks for QLoRA training (free GPU). Output is converted to GGUF locally.
- **Retrieval libraries** (sentence-transformers, rank_bm25, networkx) and **LangGraph / FastAPI / Streamlit** as those stages are built.
- **CI** (GitHub Actions): not started.
