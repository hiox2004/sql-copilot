"""The contract every database adapter must satisfy.

A `Protocol` is Python's way of saying "anything with these attributes and methods counts";
no inheritance needed. The rest of the package talks to a `Dialect`, never to a specific database,
so adding another database means writing one new adapter, not changing the pipeline.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from t2sql.core.schema_models import SchemaInfo


@dataclass(frozen=True)
class GuardPolicy:
    """What the SQL Guard must refuse for one database. Names are lowercase."""

    blocked_functions: frozenset[str]  # exact function names that are never allowed
    blocked_function_prefixes: tuple[str, ...]  # whole families, e.g. file-system helpers
    system_schemas: frozenset[str]  # schemas holding the database's own catalog
    system_table_prefixes: tuple[str, ...]  # catalog tables that need no schema prefix


class Dialect(Protocol):
    #: Short id used in profiles, e.g. the value of `dialect:` in data/profiles/<db>.yaml.
    name: str
    #: The matching dialect name for sqlglot (used by the Guard to parse generated SQL).
    sqlglot_name: str
    #: Functions, schemas and tables the Guard must refuse for this database.
    guard_policy: GuardPolicy

    def introspect(self, conn: Any, schema_name: str) -> SchemaInfo:
        """Read the structure (never rows) of one schema over an open DB-API connection."""
        ...

    def explain_statement(self, sql: str) -> str:
        """Wrap `sql` in the cheapest plan-only check the database offers (never executes it)."""
        ...
