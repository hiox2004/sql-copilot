"""PostgreSQL adapter. Dialect names are allowed here (and in data/) and nowhere else."""

from typing import Any

from t2sql.core.schema_models import SchemaInfo
from t2sql.dialects.postgres.introspect import introspect_schema


class PostgresDialect:
    name = "postgres"
    sqlglot_name = "postgres"

    def introspect(self, conn: Any, schema_name: str) -> SchemaInfo:
        return introspect_schema(conn, schema_name)

    def explain_statement(self, sql: str) -> str:
        # Plain EXPLAIN only plans the query. Never ANALYZE: that would actually run it.
        return f"EXPLAIN {sql}"
