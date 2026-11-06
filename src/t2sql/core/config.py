"""One place for settings that come from the environment (.env).

Everything environment-specific (database login, model server URL, the pinned "today") is read
here, once. Other modules receive a `Settings` object instead of calling os.environ themselves.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from psycopg.conninfo import make_conninfo

REPO_ROOT = Path(__file__).resolve().parents[3]

# The pinned "today" for seeds, checks and prompts. Keep in sync with REF_NOW in
# infra/postgres/init/02_load_schema.sh (a unit test enforces this).
DEFAULT_REF_NOW = "2026-11-05 12:00:00+00"


@dataclass(frozen=True)
class Settings:
    db_host: str
    db_port: int
    db_name: str
    ro_user: str
    ro_password: str
    admin_user: str
    admin_password: str
    llm_base_url: str
    ref_now: datetime

    @classmethod
    def from_env(cls, env_file: Path | None = REPO_ROOT / ".env") -> "Settings":
        """Read settings from the process environment, loading `.env` first if it exists."""
        if env_file is not None:
            load_dotenv(env_file)
        env = os.environ
        # POSTGRES_* / COPILOT_RO_* are the names the official Docker image and our compose file
        # dictate; this is the one place outside dialects/ that is allowed to know them.
        ref_now = datetime.fromisoformat(env.get("REF_NOW", DEFAULT_REF_NOW))
        if ref_now.tzinfo is None:
            raise ValueError(f"REF_NOW must include a timezone, got {ref_now.isoformat()!r}")
        return cls(
            # 127.0.0.1, not "localhost": on Windows "localhost" tries IPv6 first and hangs,
            # while Docker publishes the port on IPv4 only.
            db_host=env.get("DB_HOST", "127.0.0.1"),
            db_port=int(env.get("POSTGRES_PORT", "5432")),
            db_name=env.get("POSTGRES_DB", "saas"),
            ro_user=env.get("COPILOT_RO_USER", "copilot_ro"),
            ro_password=env.get("COPILOT_RO_PASSWORD", ""),
            admin_user=env.get("POSTGRES_USER", "admin"),
            admin_password=env.get("POSTGRES_PASSWORD", ""),
            llm_base_url=env.get("LLM_BASE_URL", "http://localhost:8080/v1"),
            ref_now=ref_now,
        )

    def _dsn(self, user: str, password: str) -> str:
        # make_conninfo quotes values, so a password with spaces or quotes cannot break the string.
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=user,
            password=password,
            connect_timeout=5,  # fail fast instead of hanging when the database is down
        )

    @property
    def ro_dsn(self) -> str:
        """Connection string for the read-only role: what the copilot uses at run time."""
        return self._dsn(self.ro_user, self.ro_password)

    @property
    def admin_dsn(self) -> str:
        """Admin login. Only for setup tasks, never for running generated SQL."""
        return self._dsn(self.admin_user, self.admin_password)
