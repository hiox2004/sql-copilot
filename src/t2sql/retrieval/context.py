"""Render the schema and dictionary as compact text for the model prompt.

This is what retrieval will hand to the prompt builder: a few tables (or, for a no-retrieval
baseline, all of them) described with columns, allowed values, rules and metrics. Personal-data
columns (`pii: true`) are never shown, so the model cannot even learn they exist.
"""

from collections.abc import Collection
from datetime import datetime

from t2sql.core.dictionary_models import Dictionary
from t2sql.core.metric_render import render_metric_sql
from t2sql.core.schema_models import SchemaInfo

_SHORT_TYPES = {
    "timestamp with time zone": "timestamptz",
    "timestamp without time zone": "timestamp",
    "character varying": "varchar",
    "double precision": "float",
}


def _short(data_type: str) -> str:
    return _SHORT_TYPES.get(data_type, data_type)


def render_tables(
    schema: SchemaInfo, dictionary: Dictionary, tables: Collection[str] | None = None
) -> str:
    """One block per table: description, columns with types, keys, allowed values."""
    blocked = dictionary.blocked_columns()
    wanted = set(tables) if tables is not None else None
    lines: list[str] = []
    for table in schema.tables:
        if wanted is not None and table.name not in wanted:
            continue
        entry = dictionary.tables.get(table.name)
        columns = ", ".join(
            f"{col.name} {_short(col.data_type)}"
            for col in table.columns
            if (table.name, col.name) not in blocked
        )
        head = f"TABLE {table.name}({columns})"
        if entry is not None:
            head += f" -- {entry.description}"
        lines.append(head)
        for fk in table.foreign_keys:
            cols, ref_cols = ", ".join(fk.columns), ", ".join(fk.ref_columns)
            lines.append(f"  FK {cols} -> {fk.ref_table}({ref_cols})")
        if entry is not None:
            for col_name, col in entry.columns.items():
                if (table.name, col_name) in blocked:
                    continue
                if col.values:
                    meanings = "; ".join(f"{v} = {d}" for v, d in col.values.items())
                    lines.append(f"  {col_name} values: {meanings}")
                elif col.unit == "cents":
                    lines.append(f"  {col_name} is money in cents")
    return "\n".join(lines)


def render_rules(dictionary: Dictionary) -> str:
    return "\n".join(f"- {rule.text}" for rule in dictionary.global_rules)


def render_metrics(dictionary: Dictionary, today: datetime) -> str:
    out = []
    for name, metric in dictionary.metrics.items():
        out.append(f"{name}: {metric.description}\n  SQL: {render_metric_sql(metric, today)}")
    return "\n".join(out)


def render_context(
    schema: SchemaInfo,
    dictionary: Dictionary,
    today: datetime,
    tables: Collection[str] | None = None,
) -> str:
    """Everything the model needs besides the question. `tables=None` means all tables."""
    return (
        "## Business rules\n"
        f"{render_rules(dictionary)}\n\n"
        "## Tables\n"
        f"{render_tables(schema, dictionary, tables)}\n\n"
        "## Business metrics (reference SQL)\n"
        f"{render_metrics(dictionary, today)}"
    )
