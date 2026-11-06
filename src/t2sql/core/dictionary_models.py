"""Models for the business data dictionary (one YAML file per database).

The dictionary tells the system what words MEAN (churned, revenue, client ...) and warns
about traps the schema cannot express (money in cents, PII columns). These models only
check the file by itself: shape, types, naming, size limits and internal cross-references.
Whether a table/column really exists in the database is checked later, against the DB.

Design rules (see docs/study-guide.html, "Dictionary"):
  * Unknown fields are rejected, so a typo like `synonymns:` fails loudly instead of being ignored.
  * Models are frozen: once loaded, a dictionary cannot be changed by accident.
  * Strict types: YAML turns unquoted on/off/yes/no into booleans; strict strings reject that.
  * Text is length-capped because every character costs prompt tokens on a small model.
"""

import string
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

# ---- limits (first guesses; tune after measuring real prompt sizes) ----
MAX_DESCRIPTION_CHARS = 200
MAX_SQL_CHARS = 800
MAX_SYNONYM_CHARS = 48

# Placeholders every metric may use. The prompt builder replaces {today} with the pinned date.
GLOBAL_PLACEHOLDERS = frozenset({"today"})

_IDENT_PATTERN = r"^[a-z][a-z0-9_]*$"
_TERM_PATTERN = r"^[a-z][a-z0-9 _-]*$"

Identifier = Annotated[
    str, StringConstraints(strict=True, pattern=_IDENT_PATTERN, max_length=64)
]
TermName = Annotated[
    str, StringConstraints(strict=True, pattern=_TERM_PATTERN, max_length=48)
]
Description = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=MAX_DESCRIPTION_CHARS
    ),
]
Synonym = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=MAX_SYNONYM_CHARS
    ),
]
EnumValue = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64)]
Owner = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=64)
]
SqlText = Annotated[
    str,
    StringConstraints(
        strict=True, strip_whitespace=True, min_length=1, max_length=MAX_SQL_CHARS
    ),
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Meta(_Base):
    id: Identifier
    dialect: Identifier
    version: StrictInt = Field(ge=1)


class GlobalRule(_Base):
    """A rule that applies to every question; always included in the prompt."""

    id: Identifier
    text: Description


class Column(_Base):
    description: Description | None = None
    unit: Identifier | None = None  # e.g. cents, days
    pii: StrictBool = False  # personal/sensitive: kept out of prompts and blocked by the guard
    values: dict[EnumValue, Description] = {}  # allowed value -> what it means

    @model_validator(mode="after")
    def _pii_columns_carry_no_values(self) -> "Column":
        if self.pii and self.values:
            raise ValueError("a pii column must not list values (they could leak into prompts)")
        return self


class Table(_Base):
    description: Description
    synonyms: list[Synonym] = []
    columns: dict[Identifier, Column] = {}

    @model_validator(mode="after")
    def _synonyms_are_unique(self) -> "Table":
        lowered = [s.lower() for s in self.synonyms]
        if len(lowered) != len(set(lowered)):
            raise ValueError("synonyms must be unique within a table")
        return self


class MetricParameter(_Base):
    default: StrictInt
    description: Description


class Metric(_Base):
    """A named business measure with one complete, runnable canonical query."""

    description: Description
    sql: SqlText
    owner: Owner
    rationale: Description
    parameters: dict[Identifier, MetricParameter] = {}

    @model_validator(mode="after")
    def _sql_is_a_single_select_with_known_placeholders(self) -> "Metric":
        sql = self.sql
        if not sql.lower().startswith(("select", "with")):
            raise ValueError("metric sql must start with SELECT or WITH")
        if ";" in sql:
            raise ValueError("metric sql must be a single statement (no ';')")
        used = _placeholders(sql)
        allowed = GLOBAL_PLACEHOLDERS | set(self.parameters)
        unknown = used - allowed
        if unknown:
            raise ValueError(
                f"unknown placeholder(s) {sorted(unknown)}; allowed: {sorted(allowed)}"
            )
        unused = set(self.parameters) - used
        if unused:
            raise ValueError(f"declared parameter(s) never used in sql: {sorted(unused)}")
        return self


def _placeholders(sql: str) -> set[str]:
    """Return the {names} used in sql. Only plain identifiers are allowed as placeholders."""
    names: set[str] = set()
    try:
        parsed = list(string.Formatter().parse(sql))
    except ValueError as exc:
        raise ValueError(
            f"malformed braces in sql ({exc}); write literal braces as {{{{ }}}}"
        ) from exc
    for _literal, field, spec, conversion in parsed:
        if field is None:
            continue
        if spec or conversion or not field.isidentifier() or field != field.lower():
            raise ValueError(f"invalid placeholder {{{field}}}: use plain lowercase names only")
        names.add(field)
    return names


class Term(_Base):
    """A business word that points at a table (client -> organizations)."""

    maps_to: Identifier
    note: Description | None = None


class Dictionary(_Base):
    meta: Meta
    global_rules: list[GlobalRule] = []
    tables: dict[Identifier, Table]
    metrics: dict[Identifier, Metric] = {}
    terms: dict[TermName, Term] = {}

    @model_validator(mode="after")
    def _cross_references(self) -> "Dictionary":
        if not self.tables:
            raise ValueError("tables must not be empty")

        rule_ids = [r.id for r in self.global_rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("global_rules ids must be unique")

        for term, spec in self.terms.items():
            if spec.maps_to not in self.tables:
                raise ValueError(f"term '{term}' maps_to unknown table '{spec.maps_to}'")

        owners: dict[str, str] = {}
        for table_name, table in self.tables.items():
            for syn in table.synonyms:
                key = syn.lower()
                if key in owners and owners[key] != table_name:
                    raise ValueError(
                        f"synonym '{syn}' is claimed by both '{owners[key]}' and '{table_name}'"
                    )
                owners[key] = table_name
        return self

    def blocked_columns(self) -> frozenset[tuple[str, str]]:
        """(table, column) pairs flagged pii. Feeds the SQL safety guard (layer 4)."""
        return frozenset(
            (table_name, col_name)
            for table_name, table in self.tables.items()
            for col_name, col in table.columns.items()
            if col.pii
        )
