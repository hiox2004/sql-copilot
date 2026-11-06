"""What introspection returns: a plain, database-neutral description of a schema.

These are frozen dataclasses (not Pydantic) because they are produced by our own code from the
database catalog, never parsed from a human-edited file, so there is nothing to validate.
Structure only: names, types, keys, allowed values. Never row data.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str  # as the database prints it, e.g. "integer", "timestamp with time zone"
    nullable: bool
    # Allowed values when a CHECK constraint says `col IN (...)`; empty tuple otherwise.
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ForeignKey:
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: tuple[ColumnInfo, ...]
    primary_key: tuple[str, ...] = ()
    foreign_keys: tuple[ForeignKey, ...] = ()

    def column(self, name: str) -> ColumnInfo:
        for col in self.columns:
            if col.name == name:
                return col
        raise KeyError(f"{self.name} has no column {name!r}")


@dataclass(frozen=True)
class SchemaInfo:
    tables: tuple[TableInfo, ...] = field(default_factory=tuple)

    def table(self, name: str) -> TableInfo:
        for t in self.tables:
            if t.name == name:
                return t
        raise KeyError(f"no table {name!r}")

    @property
    def table_names(self) -> frozenset[str]:
        return frozenset(t.name for t in self.tables)
