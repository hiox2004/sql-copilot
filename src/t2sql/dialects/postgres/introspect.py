"""Read a PostgreSQL schema's structure from the system catalog.

Only metadata is queried (pg_class, pg_attribute, pg_constraint): table and column names, types,
primary and foreign keys, and CHECK constraints. No table rows are ever read.
"""

import re
from collections import defaultdict
from typing import Any

from t2sql.core.schema_models import ColumnInfo, ForeignKey, SchemaInfo, TableInfo

_COLUMNS_SQL = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

_PRIMARY_KEYS_SQL = """
SELECT c.relname, a.attname
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL unnest(k.conkey) WITH ORDINALITY AS u(attnum, ord)
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = u.attnum
WHERE k.contype = 'p' AND n.nspname = %s
ORDER BY c.relname, u.ord
"""

_FOREIGN_KEYS_SQL = """
SELECT k.oid, c.relname, fc.relname, a.attname, fa.attname
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_class fc ON fc.oid = k.confrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
CROSS JOIN LATERAL unnest(k.conkey, k.confkey) WITH ORDINALITY AS u(attnum, fattnum, ord)
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = u.attnum
JOIN pg_attribute fa ON fa.attrelid = fc.oid AND fa.attnum = u.fattnum
WHERE k.contype = 'f' AND n.nspname = %s
ORDER BY k.oid, u.ord
"""

_CHECKS_SQL = """
SELECT c.relname, pg_get_constraintdef(k.oid)
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE k.contype = 'c' AND n.nspname = %s
"""

# Postgres prints `CHECK (status IN ('a','b'))` as `CHECK ((status = ANY (ARRAY['a'::text, ...])))`.
_ENUM_CHECK = re.compile(r"^CHECK \(\((\w+) = ANY \(ARRAY\[(.*)\]\)\)\)$", re.DOTALL)
_QUOTED_LITERAL = re.compile(r"'((?:[^']|'')*)'::")


def parse_enum_check(definition: str) -> tuple[str, tuple[str, ...]] | None:
    """Return (column, allowed values) if `definition` is a plain "column IN (...)" CHECK.

    Anything else (ranges, cross-column rules like `(status = 'paid') = (paid_at IS NOT NULL)`)
    returns None: those are invariants, not lists of allowed values.
    """
    match = _ENUM_CHECK.match(definition.strip())
    if match is None:
        return None
    column, body = match.groups()
    values = tuple(v.replace("''", "'") for v in _QUOTED_LITERAL.findall(body))
    return (column, values) if values else None


def introspect_schema(conn: Any, schema_name: str) -> SchemaInfo:
    """Describe every ordinary table in `schema_name`, sorted by name."""
    with conn.cursor() as cur:
        cur.execute(_COLUMNS_SQL, (schema_name,))
        column_rows = cur.fetchall()
        cur.execute(_PRIMARY_KEYS_SQL, (schema_name,))
        pk_rows = cur.fetchall()
        cur.execute(_FOREIGN_KEYS_SQL, (schema_name,))
        fk_rows = cur.fetchall()
        cur.execute(_CHECKS_SQL, (schema_name,))
        check_rows = cur.fetchall()

    enums: dict[tuple[str, str], tuple[str, ...]] = {}
    for table, definition in check_rows:
        parsed = parse_enum_check(definition)
        if parsed is not None:
            enums[(table, parsed[0])] = parsed[1]

    pks: dict[str, list[str]] = defaultdict(list)
    for table, column in pk_rows:
        pks[table].append(column)

    fk_parts: dict[int, dict[str, Any]] = {}
    for oid, table, ref_table, column, ref_column in fk_rows:
        part = fk_parts.setdefault(
            oid, {"table": table, "ref_table": ref_table, "cols": [], "ref_cols": []}
        )
        part["cols"].append(column)
        part["ref_cols"].append(ref_column)
    fks: dict[str, list[ForeignKey]] = defaultdict(list)
    for part in fk_parts.values():
        fks[part["table"]].append(
            ForeignKey(tuple(part["cols"]), part["ref_table"], tuple(part["ref_cols"]))
        )

    columns: dict[str, list[ColumnInfo]] = defaultdict(list)
    for table, name, data_type, nullable in column_rows:
        columns[table].append(ColumnInfo(name, data_type, nullable, enums.get((table, name), ())))

    return SchemaInfo(
        tables=tuple(
            TableInfo(
                name=name,
                columns=tuple(cols),
                primary_key=tuple(pks.get(name, ())),
                foreign_keys=tuple(fks.get(name, ())),
            )
            for name, cols in sorted(columns.items())
        )
    )
