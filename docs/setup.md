# Setup guide

Everything needed to get this project running on a fresh Windows machine, and how each piece works.
**This file is a living document:** every new setup step (tools, services, environments) is appended here when it is introduced.

Last updated: 2026-11-05.

## Status at a glance

| Piece | Status | Section |
|---|---|---|
| Git repo (public, MIT) | Done | [Repository](#repository) |
| Python 3.12 virtual environment + `t2sql` package (editable) | Done | [Python](#python-environment) |
| Postgres 16 in Docker (36 tables, seeded) | Done | [Docker](#docker-compose) |
| pgAdmin (database browser) | Done, optional | [pgAdmin](#pgadmin-optional-database-browser) |
| Snapshots and scratch database | Done | [Snapshots](#snapshots-and-the-scratch-database) |
| Claude Code tutor agent + `teach` skill | Done | [Claude Code](#claude-code) |
| `pyproject.toml`, pytest, ruff | Done (5 tests passing) | [Python](#python-environment) |
| llama.cpp (local model serving) | Planned | [Planned](#planned-setups-not-done-yet) |
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

Optional override read by the DB loader: `REF_NOW` (the pinned "today", default `2026-11-05 12:00:00+00`).

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
3. `99_checks.sql` runs 35 consistency queries. **If any rule is violated it raises an error and the whole initialisation fails** (the container will not become healthy).
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
| Windows blocks `Activate.ps1` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |

## Planned setups (not done yet)

These are decided but not installed. Each gets a full section above when it is done.

- **llama.cpp** for local model serving: `llama-server` with a GGUF file on the 4 GB GPU, OpenAI-compatible API on `localhost:8080`. Native Windows binary, not Docker.
- **Colab / Kaggle** notebooks for QLoRA training (free GPU). Output is converted to GGUF locally.
- **Retrieval libraries** (sentence-transformers, rank_bm25, networkx) and **LangGraph / FastAPI / Streamlit** as those stages are built.
- **CI** (GitHub Actions): not started.
