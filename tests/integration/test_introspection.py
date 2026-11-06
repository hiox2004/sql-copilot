"""Introspection against the real database, as the READ-ONLY role. Skipped if it is not running."""

import psycopg
import pytest

from t2sql.core.config import Settings
from t2sql.dialects import get_dialect
from t2sql.retrieval.dictionary import parse_dictionary
from t2sql.retrieval.draft_dictionary import draft_dictionary_yaml

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def schema():
    settings = Settings.from_env()
    try:
        conn = psycopg.connect(settings.ro_dsn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    with conn:
        yield get_dialect("postgres").introspect(conn, "public")


def test_finds_all_36_tables(schema):
    assert len(schema.tables) == 36


def test_primary_and_foreign_keys(schema):
    subscriptions = schema.table("subscriptions")
    assert subscriptions.primary_key == ("id",)
    assert any(
        fk.ref_table == "organizations" and fk.columns == ("org_id",)
        for fk in subscriptions.foreign_keys
    )


def test_every_foreign_key_points_at_a_real_table(schema):
    for table in schema.tables:
        for fk in table.foreign_keys:
            assert fk.ref_table in schema.table_names, f"{table.name} -> {fk.ref_table}"


def test_enum_values_come_from_check_constraints(schema):
    status = schema.table("subscriptions").column("status")
    assert status.enum_values == ("trialing", "active", "past_due", "canceled")


def test_cross_column_checks_do_not_become_enums(schema):
    # `status = 'paid' <=> paid_at IS NOT NULL` is an invariant, so paid_at has no enum values.
    assert schema.table("invoices").column("paid_at").enum_values == ()


def test_draft_from_the_real_schema_loads_and_covers_every_table(schema):
    d = parse_dictionary(draft_dictionary_yaml(schema, "saas", "postgres"))
    assert set(d.tables) == schema.table_names
