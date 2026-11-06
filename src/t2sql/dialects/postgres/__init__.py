"""PostgreSQL adapter. Dialect names are allowed here (and in data/) and nowhere else."""

from typing import Any

from t2sql.core.schema_models import SchemaInfo
from t2sql.dialects.base import GuardPolicy
from t2sql.dialects.postgres.introspect import introspect_schema


class PostgresDialect:
    name = "postgres"
    sqlglot_name = "postgres"
    guard_policy = GuardPolicy(
        allowed_anonymous_functions=frozenset({"age", "date_bin", "split_part"}),
        blocked_functions=frozenset(
            {
                "set_config", "current_setting", "dblink", "query_to_xml", "xpath",
                "current_user", "session_user", "current_database", "current_catalog",
                "current_schema", "current_version",
                "repeat", "pad",  # memory bombs: repeat('x', 100000000), lpad(..., 100000000)
            }
        ),
        blocked_function_prefixes=("pg_", "lo_", "dblink_", "txid_"),
        system_schemas=frozenset({"pg_catalog", "information_schema", "pg_toast"}),
        system_table_prefixes=("pg_",),
        default_schema="public",
    )

    def introspect(self, conn: Any, schema_name: str) -> SchemaInfo:
        return introspect_schema(conn, schema_name)

    def explain_statement(self, sql: str) -> str:
        # Plain EXPLAIN only plans the query. Never ANALYZE: that would actually run it.
        return f"EXPLAIN {sql}"
