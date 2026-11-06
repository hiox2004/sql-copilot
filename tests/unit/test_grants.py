"""The generated read-only privileges must leave out personal-data columns."""

from t2sql.core.config import REPO_ROOT
from t2sql.core.schema_models import ColumnInfo, SchemaInfo, TableInfo
from t2sql.dialects.postgres.grants import render_readonly_grants

SCHEMA = SchemaInfo(
    tables=(
        TableInfo("users", (ColumnInfo("id", "int", False), ColumnInfo("email", "text", False))),
        TableInfo("orders", (ColumnInfo("id", "int", False),)),
        TableInfo("secrets", (ColumnInfo("token", "text", False),)),
    )
)


def test_pii_column_is_left_out_of_the_grant():
    text = render_readonly_grants(SCHEMA, {("users", "email")})
    assert 'GRANT SELECT ("id") ON "users"' in text
    assert "email" not in text.split("REVOKE ALL")[1]


def test_clean_table_gets_a_plain_grant():
    assert 'GRANT SELECT ON "orders" TO :"ro_user";' in render_readonly_grants(SCHEMA, set())


def test_table_made_only_of_personal_data_gets_no_grant():
    text = render_readonly_grants(SCHEMA, {("secrets", "token")})
    assert '"secrets"' not in text


def test_everything_is_revoked_first():
    text = render_readonly_grants(SCHEMA, set())
    assert text.index("REVOKE ALL") < text.index("GRANT SELECT")


def test_role_name_is_a_variable_not_hard_coded():
    assert "TO copilot_ro" not in render_readonly_grants(SCHEMA, set())


def test_committed_grants_file_has_no_blocked_column():
    from t2sql.retrieval.dictionary import load_dictionary

    committed = (REPO_ROOT / "data" / "schema" / "grants" / "copilot_ro.sql").read_text("utf-8")
    dictionary = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
    for table, column in dictionary.blocked_columns():
        for line in committed.splitlines():
            if f'ON "{table}"' in line:
                assert f'"{column}"' not in line, f"{table}.{column} is granted"
