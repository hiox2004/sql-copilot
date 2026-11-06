"""Regenerate data/schema/grants/copilot_ro.sql (the read-only role's column-level privileges).

Usage (venv active, database running):   python scripts/gen_column_grants.py
Run it whenever the schema or a `pii` flag in the dictionary changes. A test fails if the committed
file is out of date. To apply to a running database:
    MSYS_NO_PATHCONV=1 docker exec t2sql-postgres psql -U admin -d saas -v ro_user=copilot_ro \
        -f /schema/grants/copilot_ro.sql
(New volumes get it automatically from infra/postgres/init/02_load_schema.sh.)
"""

import sys

import psycopg

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.dialects.postgres import PostgresDialect
from t2sql.dialects.postgres.grants import render_readonly_grants
from t2sql.retrieval.dictionary import load_dictionary


def main() -> int:
    profile = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
    dictionary = load_dictionary(REPO_ROOT / profile.dictionary)
    with psycopg.connect(Settings.from_env().ro_dsn) as conn:
        schema = PostgresDialect().introspect(conn, profile.schema_name)
    out = REPO_ROOT / "data" / "schema" / "grants" / "copilot_ro.sql"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_readonly_grants(schema, dictionary.blocked_columns()), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
