"""The finished dictionary must agree with the real database (step 5).

The loader (step 2) only checks the file against itself. These tests catch the mistakes it cannot:
a table that does not exist (e.g. `organisations`), a missing table, a wrong enum value, a metric
that does not run. Everything runs as the READ-ONLY role.
"""

import psycopg
import pytest

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.metric_render import render_metric_sql
from t2sql.core.profile import load_profile
from t2sql.dialects import get_dialect
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.retrieval.draft_dictionary import is_money_column

pytestmark = pytest.mark.integration

SETTINGS = Settings.from_env()
PROFILE = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
DICTIONARY = load_dictionary(REPO_ROOT / PROFILE.dictionary)


@pytest.fixture(scope="module")
def conn():
    try:
        connection = psycopg.connect(SETTINGS.ro_dsn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    yield connection
    connection.close()


@pytest.fixture(scope="module")
def schema(conn):
    return get_dialect(PROFILE.dialect).introspect(conn, PROFILE.schema_name)


def test_every_dictionary_table_exists(schema):
    missing = set(DICTIONARY.tables) - schema.table_names
    assert not missing, f"dictionary names tables the database does not have: {sorted(missing)}"


def test_every_database_table_is_documented(schema):
    undocumented = schema.table_names - set(DICTIONARY.tables)
    assert not undocumented, f"tables without a dictionary entry: {sorted(undocumented)}"


def test_every_dictionary_column_exists(schema):
    for table_name, table in DICTIONARY.tables.items():
        real = {c.name for c in schema.table(table_name).columns}
        unknown = set(table.columns) - real
        assert not unknown, f"{table_name}: unknown columns {sorted(unknown)}"


def test_enum_values_match_the_check_constraints_exactly(schema):
    for table_name, table in DICTIONARY.tables.items():
        for col_name, col in table.columns.items():
            if not col.values:
                continue
            real = set(schema.table(table_name).column(col_name).enum_values)
            assert real, f"{table_name}.{col_name} lists values but the database has no CHECK list"
            assert set(col.values) == real, (
                f"{table_name}.{col_name}: dictionary {sorted(col.values)} "
                f"!= database {sorted(real)}"
            )


def test_every_constrained_column_has_its_values_documented(schema):
    # The reverse direction: a CHECK-constrained column must not be silently skipped.
    for table in schema.tables:
        for col in table.columns:
            if col.enum_values:
                documented = DICTIONARY.tables[table.name].columns.get(col.name)
                assert documented is not None and documented.values, (
                    f"{table.name}.{col.name}: allowed values in the DB, none in the dictionary"
                )


def test_money_columns_declare_cents_both_ways(schema):
    for table in schema.tables:
        for col in table.columns:
            documented = DICTIONARY.tables[table.name].columns.get(col.name)
            declared = documented is not None and documented.unit == "cents"
            money = is_money_column(col.name)
            assert declared == money, (
                f"{table.name}.{col.name}: unit cents declared={declared}, name looks money={money}"
            )


@pytest.mark.parametrize("metric_name", sorted(DICTIONARY.metrics))
def test_every_metric_runs_and_returns_one_value(conn, metric_name):
    sql = render_metric_sql(DICTIONARY.metrics[metric_name], SETTINGS.ref_now)
    row = conn.execute(sql).fetchone()
    conn.rollback()
    assert row is not None and len(row) == 1, f"{metric_name} must return one row, one column"
    assert row[0] is not None, f"{metric_name} returned NULL (no matching rows?)"


def test_metric_window_parameter_changes_the_answer(conn):
    metric = DICTIONARY.metrics["active_users"]
    short = conn.execute(render_metric_sql(metric, SETTINGS.ref_now, window_days=1)).fetchone()[0]
    long = conn.execute(render_metric_sql(metric, SETTINGS.ref_now, window_days=90)).fetchone()[0]
    conn.rollback()
    assert short <= long
