"""The executor against the real database, as the read-only role."""

import psycopg
import pytest

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.dialects import get_dialect
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.executor import QueryTimeout, run_guarded
from t2sql.validation.guard import GuardViolation, guard_sql
from t2sql.validation.redteam import load_redteam

pytestmark = pytest.mark.integration

SETTINGS = Settings.from_env()
DICTIONARY = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
REDTEAM = load_redteam(REPO_ROOT / "data" / "eval" / "redteam.yaml")


@pytest.fixture()
def conn():
    try:
        connection = psycopg.connect(SETTINGS.ro_dsn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    yield connection
    connection.close()


def test_runs_a_query_and_returns_columns_and_rows(conn):
    result = run_guarded(conn, "SELECT status, count(*) AS n FROM subscriptions GROUP BY status")
    assert result.columns == ("status", "n")
    assert {row[0] for row in result.rows} == {"trialing", "active", "past_due", "canceled"}


def test_timeout_is_enforced_even_though_the_session_could_disable_it(conn):
    # Bypasses the Guard on purpose: this tests the executor's own timeout.
    with pytest.raises(QueryTimeout):
        run_guarded(conn, "SELECT pg_sleep(5)", timeout_ms=200)


def test_connection_is_usable_after_a_timeout(conn):
    with pytest.raises(QueryTimeout):
        run_guarded(conn, "SELECT pg_sleep(5)", timeout_ms=200)
    assert run_guarded(conn, "SELECT 1").rows == ((1,),)


def test_timeout_does_not_leak_to_the_next_query(conn):
    run_guarded(conn, "SELECT 1", timeout_ms=200)
    assert conn.execute("SHOW statement_timeout").fetchone()[0] == "10s"
    conn.rollback()


@pytest.mark.parametrize("bad", [0, -5, True, "10"])
def test_timeout_must_be_a_positive_integer(conn, bad):
    with pytest.raises(ValueError, match="positive integer"):
        run_guarded(conn, "SELECT 1", timeout_ms=bad)


def test_writes_fail_inside_the_executor_too(conn):
    with pytest.raises(psycopg.Error):
        run_guarded(conn, "DELETE FROM users")


def test_every_rejected_red_team_attack_is_rejected_before_reaching_the_database():
    # Whole pipeline slice: Guard first. Attacks that must be refused never get to the executor.
    dialect = get_dialect("postgres")
    refused = 0
    for item in REDTEAM.items:
        if not item.sql or item.blocked_by == ["guard_limits"]:
            continue
        with pytest.raises(GuardViolation):
            guard_sql(
                item.sql,
                sqlglot_dialect=dialect.sqlglot_name,
                allowed_tables=set(DICTIONARY.tables),
                blocked_columns=DICTIONARY.blocked_columns(),
            )
        refused += 1
    assert refused == 25  # all attacks with SQL except dos_cross_join (limited, not refused)


def test_limited_query_returns_at_most_max_rows(conn):
    guarded = guard_sql(
        "SELECT * FROM api_requests_daily a, feature_usage_daily b",
        sqlglot_dialect="postgres",
        allowed_tables=set(DICTIONARY.tables),
        blocked_columns=DICTIONARY.blocked_columns(),
        max_rows=50,
    )
    assert len(run_guarded(conn, guarded.sql).rows) == 50
