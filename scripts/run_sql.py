"""Try a SQL query the safe way: through the Guard, then the read-only executor.

Usage (venv active, database running):
    python scripts/run_sql.py "SELECT status, count(*) FROM subscriptions GROUP BY status"
Prints the guarded SQL actually run and up to --rows result rows. Refused queries print the rule.
"""

import argparse
import sys

import psycopg

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.dialects import get_dialect
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.executor import QueryTimeout, run_guarded
from t2sql.validation.guard import GuardViolation, guard_sql


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sql")
    parser.add_argument("--profile", default="saas")
    parser.add_argument("--rows", type=int, default=10)
    args = parser.parse_args()

    profile = load_profile(REPO_ROOT / "data" / "profiles" / f"{args.profile}.yaml")
    dictionary = load_dictionary(REPO_ROOT / profile.dictionary)
    dialect = get_dialect(profile.dialect)
    try:
        guarded = guard_sql(
            args.sql,
            dialect=dialect,
            allowed_tables=set(dictionary.tables),
            blocked_columns=dictionary.blocked_columns(),
        )
    except GuardViolation as exc:
        print(f"REFUSED by guard: {exc}")
        return 2
    print(f"-- guarded SQL: {guarded.sql}")
    with psycopg.connect(Settings.from_env().ro_dsn) as conn:
        try:
            result = run_guarded(conn, guarded.sql)
        except QueryTimeout as exc:
            print(f"TIMEOUT: {exc}")
            return 3
        except psycopg.Error as exc:
            print(f"DATABASE ERROR: {exc}".strip())
            return 4
    print(f"-- columns: {result.columns}  rows: {len(result.rows)}")
    for row in result.rows[: args.rows]:
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
