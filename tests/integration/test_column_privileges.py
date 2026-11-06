"""The database itself must refuse personal-data columns to the read-only role (second lock)."""

import psycopg
import pytest

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.dialects.postgres import PostgresDialect
from t2sql.dialects.postgres.grants import render_readonly_grants
from t2sql.retrieval.dictionary import load_dictionary

pytestmark = pytest.mark.integration

SETTINGS = Settings.from_env()
DICTIONARY = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
BLOCKED = sorted(DICTIONARY.blocked_columns())


@pytest.fixture(scope="module")
def conn():
    try:
        connection = psycopg.connect(SETTINGS.ro_dsn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    yield connection
    connection.close()


@pytest.mark.parametrize(("table", "column"), BLOCKED)
def test_blocked_column_is_unreadable(conn, table, column):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(f'SELECT "{column}" FROM "{table}"')
    conn.rollback()


@pytest.mark.parametrize("sql", ["SELECT * FROM users", "SELECT t.* FROM employees t"])
def test_star_on_a_table_with_personal_data_is_denied(conn, sql):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(sql)
    conn.rollback()


def test_the_xml_dump_bypass_is_denied_by_the_database_too(conn):
    # Even a function the Guard missed cannot read what the role has no privilege for.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT table_to_xml('users', true, false, '')")
    conn.rollback()


def test_ordinary_columns_and_counts_still_work(conn):
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] > 0
    assert conn.execute("SELECT id, role FROM users LIMIT 1").fetchone() is not None
    conn.rollback()


def test_committed_grants_file_matches_what_the_generator_would_write(conn):
    schema = PostgresDialect().introspect(conn, "public")
    expected = render_readonly_grants(schema, DICTIONARY.blocked_columns())
    committed = (REPO_ROOT / "data" / "schema" / "grants" / "copilot_ro.sql").read_text("utf-8")
    assert committed == expected, "run: python scripts/gen_column_grants.py"
