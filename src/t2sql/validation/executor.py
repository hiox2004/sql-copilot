"""Run guarded SQL: the last step of the Guard stage.

This is where the *timeout* is enforced by our own code. The database role has a default timeout,
but a session may disable it with `SET statement_timeout = 0` (a verified gap). So the executor sets
it itself, inside the transaction, after the Guard has already refused any SET from the model.

Every query runs in a READ ONLY transaction that is always rolled back.
"""

from dataclasses import dataclass
from typing import Any

import psycopg

DEFAULT_TIMEOUT_MS = 10_000


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


class QueryTimeout(Exception):
    """The query ran longer than the allowed time and was cancelled by the database."""


def run_guarded(
    conn: "psycopg.Connection", sql: str, *, timeout_ms: int = DEFAULT_TIMEOUT_MS
) -> QueryResult:
    """Execute `sql` (already approved by `guard_sql`) and return all rows.

    `timeout_ms` is an int that we format into SQL, never text from the model.
    """
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                # SET LOCAL lasts only for this transaction, so it cannot leak into other queries.
                cur.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
                cur.execute(sql)
                columns = tuple(d.name for d in cur.description or ())
                rows = tuple(cur.fetchall())
            # Leave the transaction by raising so nothing could ever be committed.
            raise _Rollback
    except _Rollback:
        pass
    except psycopg.errors.QueryCanceled as exc:
        raise QueryTimeout(f"query exceeded {timeout_ms} ms") from exc
    return QueryResult(columns, rows)


class _Rollback(Exception):
    """Internal: forces the transaction block above to roll back after reading."""
