"""Turn an introspected schema into a *draft* dictionary YAML for a human to fill in.

The draft contains the facts the database already knows (table names, allowed enum values, money
columns) and marks everything a person must decide with TODO. It is valid enough to load, so the
loader and tests can run on it from day one.

Only columns that need explaining get an entry: enum columns, money columns (`*_cents`) and
suspected personal data. Plain columns are left to the schema text, which keeps the dictionary
small.
"""

import json
import re

from t2sql.core.schema_models import ColumnInfo, SchemaInfo

# Column names that usually hold personal data. A heuristic: a human confirms every flag.
_PII_NAME = re.compile(
    r"(^|_)(email|phone|mobile|ssn|dob|birth\w*|address|street|zip|postal|ip|ip_address"
    r"|first_name|last_name|full_name|password|token)($|_)"
)
_YAML_WORDS = {"on", "off", "yes", "no", "true", "false", "null", "y", "n", "~"}


def looks_like_pii(column_name: str) -> bool:
    return _PII_NAME.search(column_name) is not None


def _q(text: str) -> str:
    """Always-quoted YAML string (JSON strings are valid YAML), so on/off/yes/no stay strings."""
    return json.dumps(text, ensure_ascii=False)


def _key(text: str) -> str:
    return _q(text) if text.lower() in _YAML_WORDS else text


def _column_block(col: ColumnInfo) -> list[str]:
    lines: list[str] = []
    pii = looks_like_pii(col.name)
    money = col.name.endswith("_cents")
    if not (col.enum_values or pii or money):
        return lines
    lines.append(f"      {_key(col.name)}:")
    if pii:
        lines.append("        pii: true  # TODO confirm: suspected personal data")
    elif col.enum_values:
        lines.append('        description: "TODO"')
    if money:
        lines.append("        unit: cents")
        lines.append('        description: "TODO"')
    if col.enum_values and not pii:
        lines.append("        values:")
        for value in col.enum_values:
            lines.append(f'          {_q(value)}: "TODO"')
    return lines


def draft_dictionary_yaml(schema: SchemaInfo, dictionary_id: str, dialect: str) -> str:
    out = [
        f"# DRAFT dictionary for '{dictionary_id}', generated from the database structure.",
        "# Fill every TODO, then save as <id>.yaml. Never put row data or real personal data here.",
        "meta:",
        f"  id: {dictionary_id}",
        f"  dialect: {dialect}",
        "  version: 1",
        "",
        "global_rules: []  # TODO: rules that apply to every question (money units, pinned date)",
        "",
        "tables:",
    ]
    for table in schema.tables:
        out.append(f"  {_key(table.name)}:")
        out.append('    description: "TODO"')
        out.append("    synonyms: []  # TODO: words people use for this table")
        column_lines = [line for col in table.columns for line in _column_block(col)]
        if column_lines:
            out.append("    columns:")
            out.extend(column_lines)
        out.append("")
    out.extend(
        [
            "metrics: {}  # TODO: business definitions as one complete SELECT each",
            "terms: {}  # TODO: business words that point at a table",
            "",
        ]
    )
    return "\n".join(out)
