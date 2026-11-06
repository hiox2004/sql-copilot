"""Verify stage: ask the database to PLAN the query (EXPLAIN), and explain errors to the model.

Why: a small model often invents a column. Planning finds that in milliseconds without running the
query, and the error plus the REAL column list lets the model fix itself (the repair loop).

Never EXPLAIN ANALYZE: that would execute the query. Only plain EXPLAIN.
"""

import difflib
import re
from collections.abc import Collection
from dataclasses import dataclass

import psycopg
import sqlglot
from sqlglot import exp

from t2sql.core.schema_models import SchemaInfo
from t2sql.dialects.base import Dialect
from t2sql.validation.guard import GuardViolation, guard_sql

EXPLAIN_TIMEOUT_MS = 5_000
# Names in a database error: "quoted" ones, or alias.column pairs such as t1.score.
_NAMES = re.compile(r'"([^"]{1,64})"|[A-Za-z_]\w*\.([A-Za-z_]\w*)')


@dataclass(frozen=True)
class Verdict:
    ok: bool
    sql: str  # the guarded SQL (LIMIT added when needed) when ok, else the input
    error: str = ""  # one short line the model can act on


def verify_sql(
    conn: "psycopg.Connection",
    sql: str,
    *,
    dialect: Dialect,
    allowed_tables: Collection[str],
    blocked_columns: Collection[tuple[str, str]] = (),
) -> Verdict:
    """Guard first (cheap, no database), then EXPLAIN (finds bad columns, types, syntax)."""
    try:
        guarded = guard_sql(
            sql,
            dialect=dialect,
            allowed_tables=allowed_tables,
            blocked_columns=blocked_columns,
        )
    except GuardViolation as exc:
        return Verdict(False, sql, f"not allowed: {exc.message}")
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {EXPLAIN_TIMEOUT_MS}")
                cur.execute(dialect.explain_statement(guarded.sql))
            raise _Rollback
    except _Rollback:
        pass
    except psycopg.Error as exc:
        return Verdict(False, sql, str(exc).strip().splitlines()[0][:200])
    return Verdict(True, guarded.sql)


class _Rollback(Exception):
    """Internal: EXPLAIN changes nothing, but we still end the transaction by rolling back."""


def repair_hint(
    error: str,
    sql: str,
    schema: SchemaInfo,
    *,
    sqlglot_dialect: str,
    blocked_columns: Collection[tuple[str, str]] = (),
    max_tables: int = 6,
) -> str:
    """Facts that help fix the error: real columns of the tables used, and where a name lives.

    Built only from the schema (never row data) and never mentions blocked (personal) columns.
    """
    blocked = set(blocked_columns)
    visible = {
        t.name: [c.name for c in t.columns if (t.name, c.name) not in blocked]
        for t in schema.tables
    }
    try:
        used = [
            t.name.lower()
            for t in sqlglot.parse_one(sql, read=sqlglot_dialect).find_all(exp.Table)
            if t.name
        ]
    except sqlglot.errors.SqlglotError:
        used = []
    used = [name for name in dict.fromkeys(used) if name in visible][:max_tables]
    lines: list[str] = []
    for quoted, qualified in dict.fromkeys(_NAMES.findall(error)):
        name = (quoted or qualified).split(".")[-1]
        homes = sorted(t for t, cols in visible.items() if name in cols)
        if homes:
            lines.append(
                f'"{name}" is not in the tables you used; it exists in: {", ".join(homes)}.'
            )
            continue
        pool = {c for t in used for c in visible[t]}
        close = difflib.get_close_matches(name, sorted(pool), n=3, cutoff=0.6)
        if close:
            lines.append(f'"{name}" does not exist; did you mean: {", ".join(close)}?')
    for name in used:
        lines.append(f"{name} columns: {', '.join(visible[name])}")
    return "\n".join(lines)


def tables_in_sql(sql: str, sqlglot_dialect: str, known: Collection[str]) -> list[str]:
    """Known tables a query reads, in order of first use (CTE names excluded)."""
    try:
        tree = sqlglot.parse_one(sql, read=sqlglot_dialect)
    except sqlglot.errors.SqlglotError:
        return []
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    names = (t.name.lower() for t in tree.find_all(exp.Table) if t.name)
    return [n for n in dict.fromkeys(names) if n in set(known) and n not in ctes]
