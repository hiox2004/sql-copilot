"""Safety layers 2-4: parse the generated SQL and decide whether it may run.

Layer 1 (the read-only database role) lives in the database. This module is the next line of
defense and works on the SQL text *before* it ever reaches the database:

  - exactly one statement, and it must be a plain SELECT (or WITH ... SELECT / UNION of SELECTs);
  - nothing that writes or changes settings anywhere in the tree (a DELETE hidden in a CTE still
    parses as a "Select" at the root, so the whole tree is inspected, not just the root);
  - no dangerous functions (sleep, file access, ...) and no system catalogs;
  - only tables the dictionary knows about;
  - no column flagged `pii` in the dictionary, including through `SELECT *`;
  - a LIMIT is always present and never larger than `max_rows`.

`guard_sql` returns the (possibly rewritten) SQL or raises `GuardViolation`.
"""

from collections.abc import Collection
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from t2sql.dialects.base import Dialect, GuardPolicy

DEFAULT_MAX_ROWS = 1000

# Anything that writes, changes structure, changes settings or runs a command.
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Copy,
    exp.Set,
    exp.Command,
    exp.Into,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Use,
    exp.Lock,  # SELECT ... FOR UPDATE takes row locks
)


class GuardViolation(Exception):
    """The SQL was refused. `rule` is a short machine-friendly name; the message explains."""

    def __init__(self, rule: str, message: str):
        super().__init__(f"[{rule}] {message}")
        self.rule = rule
        self.message = message


@dataclass(frozen=True)
class GuardResult:
    sql: str  # the SQL that is safe to send (LIMIT enforced)
    limit_added: bool  # True when the guard had to add or lower the LIMIT


def guard_sql(
    sql: str,
    *,
    dialect: Dialect,
    allowed_tables: Collection[str],
    blocked_columns: Collection[tuple[str, str]] = (),
    max_rows: int = DEFAULT_MAX_ROWS,
) -> GuardResult:
    tree = _parse_single_statement(sql, dialect.sqlglot_name)
    policy = dialect.guard_policy
    while isinstance(tree, exp.Subquery) and not tree.args.get("alias"):
        tree = tree.this  # "(SELECT ...)" as the whole statement: judge the SELECT inside it

    if not isinstance(tree, exp.Select | exp.Union | exp.Subquery):
        raise GuardViolation("not_select", f"only SELECT is allowed, got {type(tree).__name__}")

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise GuardViolation(
                "forbidden_statement", f"{type(node).__name__} is not allowed in a query"
            )
        if isinstance(node, exp.Func):
            _check_function(node, policy)

    tables = _check_tables(tree, {t.lower() for t in allowed_tables}, policy)
    _check_pii(tree, tables, {(t.lower(), c.lower()) for t, c in blocked_columns})
    return _enforce_limit(tree, dialect.sqlglot_name, max_rows)


def _parse_single_statement(sql: str, dialect: str) -> exp.Expression:
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except SqlglotError as exc:
        raise GuardViolation("unparseable", f"cannot parse the SQL: {exc}") from exc
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise GuardViolation("multiple_statements", f"expected 1 statement, got {len(statements)}")
    return statements[0]


def _check_function(node: exp.Func, policy: GuardPolicy) -> None:
    anonymous = isinstance(node, exp.Anonymous)
    name = (node.name if anonymous else node.sql_name()).lower()
    if name in policy.blocked_functions or name.startswith(policy.blocked_function_prefixes):
        raise GuardViolation("blocked_function", f"function {name}() is not allowed")
    if anonymous and name not in policy.allowed_anonymous_functions:
        raise GuardViolation(
            "function_not_allowed", f"function {name}() is not on the allowed list"
        )


def _check_tables(
    tree: exp.Expression, allowed: set[str], policy: GuardPolicy
) -> dict[str, str]:
    """Return {alias or name: real table name} and reject unknown or system tables."""
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    scope: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            continue  # a table-valued function such as generate_series(); _check_function vets it
        name = table.name.lower()
        in_system_schema = bool(table.db) and table.db.lower() in policy.system_schemas
        if in_system_schema or name.startswith(policy.system_table_prefixes):
            raise GuardViolation("system_table", f"system table {name!r} is not allowed")
        if name in cte_names and not table.db:
            continue  # a reference to a WITH ... AS name, not a real table
        if table.db and table.db.lower() != policy.default_schema:
            raise GuardViolation("unknown_schema", f"schema {table.db!r} is not allowed")
        if name not in allowed:
            raise GuardViolation("unknown_table", f"table {name!r} is not in the dictionary")
        # One flat alias map is only correct if no alias means two different tables. Refuse the
        # ambiguous case instead of guessing: a wrong guess could let personal data through.
        for key in ((table.alias_or_name or name).lower(), name):
            if scope.setdefault(key, name) != name:
                raise GuardViolation(
                    "ambiguous_alias", f"{key!r} names more than one table; use distinct aliases"
                )
    return scope


def _check_pii(
    tree: exp.Expression, scope: dict[str, str], blocked: set[tuple[str, str]]
) -> None:
    if not blocked:
        return
    tables_in_query = set(scope.values())
    blocked_here = {(t, c) for t, c in blocked if t in tables_in_query}
    if not blocked_here:
        return

    for star in tree.find_all(exp.Star):
        if isinstance(star.parent, exp.Count):
            continue  # COUNT(*) reads no column values
        qualifier = star.parent.table.lower() if isinstance(star.parent, exp.Column) else None
        if qualifier is None or scope.get(qualifier) in {t for t, _ in blocked_here}:
            raise GuardViolation(
                "pii_star", "SELECT * would include personal-data columns; list columns instead"
            )

    blocked_names = {c for _, c in blocked_here}
    tables_with_pii = {t for t, _ in blocked_here}
    for column in tree.find_all(exp.Column):
        name = column.name.lower()
        # A bare table alias used as a value, e.g. row_to_json(u), returns the whole row.
        if not column.table and scope.get(name) in tables_with_pii:
            raise GuardViolation(
                "pii_whole_row", f"{name!r} would expose a whole row including personal data"
            )
        if name not in blocked_names:
            continue
        qualifier = column.table.lower() if column.table else None
        tables = {scope[qualifier]} if qualifier in scope else tables_in_query
        if any((t, name) in blocked_here for t in tables):
            raise GuardViolation("pii_column", f"column {name!r} holds personal data")


def _enforce_limit(tree: exp.Expression, dialect: str, max_rows: int) -> GuardResult:
    current = tree.args.get("limit")
    value = _literal_int(current.expression) if isinstance(current, exp.Limit) else None
    if value is not None and value <= max_rows:
        return GuardResult(tree.sql(dialect=dialect), limit_added=False)
    limited = tree.limit(max_rows, copy=True)
    return GuardResult(limited.sql(dialect=dialect), limit_added=True)


def _literal_int(node: exp.Expression) -> int | None:
    if isinstance(node, exp.Literal) and not node.is_string:
        try:
            return int(node.this)
        except ValueError:
            return None
    return None
