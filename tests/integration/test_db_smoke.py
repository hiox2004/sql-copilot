"""Integration smoke tests against the Docker Postgres, connecting as the READ-ONLY role.

Skipped automatically when the database is not reachable.
Run:  pytest -m integration     (or plain `pytest`, which includes them)
"""

import os

import psycopg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def ro_conn():
    try:
        conn = psycopg.connect(
            host="127.0.0.1",
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            dbname=os.getenv("POSTGRES_DB", "saas"),
            user=os.getenv("COPILOT_RO_USER", "copilot_ro"),
            password=os.environ["COPILOT_RO_PASSWORD"],
            connect_timeout=3,
        )
    except (psycopg.OperationalError, KeyError) as exc:
        pytest.skip(f"database not reachable or .env missing: {exc}")
    yield conn
    conn.close()


def test_database_has_36_tables(ro_conn):
    row = ro_conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchone()
    assert row[0] == 36


def test_read_only_role_cannot_write(ro_conn):
    # Safety layer 1: the database itself refuses writes, whatever SQL we send.
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        ro_conn.execute("INSERT INTO features (key, name, category) VALUES ('x', 'x', 'x')")
    ro_conn.rollback()


def test_no_data_is_dated_after_the_pinned_today(ro_conn):
    # Regression guard for the pinned-date decision (2026-11-05 12:00 UTC).
    row = ro_conn.execute(
        "SELECT count(*) FROM orders WHERE created_at > '2026-11-05 12:00:00+00'"
    ).fetchone()
    assert row[0] == 0
