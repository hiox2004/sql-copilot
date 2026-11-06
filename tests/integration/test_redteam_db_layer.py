"""Safety layer 1 for real: every red-team attack assigned to `db_role` must be refused by the
database itself, using the READ-ONLY login. This is the one layer that exists today.

Each attack runs in its own connection and is always rolled back. If the role were ever
misconfigured, a rollback still undoes DDL (Postgres DDL is transactional), and the row counts are
checked afterwards.
"""

import psycopg
import pytest

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.validation.redteam import load_redteam

pytestmark = pytest.mark.integration

SETTINGS = Settings.from_env()
ITEMS = load_redteam(REPO_ROOT / "data" / "eval" / "redteam.yaml").blocked_by("db_role")


def _connect():
    try:
        return psycopg.connect(SETTINGS.ro_dsn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")


def _counts(conn):
    return {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("users", "payments", "orders", "subscriptions", "organizations")
    }


def test_there_are_db_layer_attacks():
    assert len(ITEMS) >= 10


@pytest.mark.parametrize("item", ITEMS, ids=lambda item: item.id)
def test_database_refuses_the_attack(item):
    conn = _connect()
    before = _counts(conn)
    conn.rollback()
    refused = False
    try:
        # Statements run one after another, like a stacked attack would. Some statement must fail.
        for statement in (s.strip() for s in item.sql.split(";") if s.strip()):
            conn.execute(statement)
    except psycopg.Error:
        refused = True
    finally:
        conn.rollback()
    after = _counts(conn)
    conn.close()
    assert refused, f"{item.id}: the database ran the whole attack without complaint"
    assert before == after, f"{item.id}: data changed!"


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM users WHERE false",
        "UPDATE users SET role = 'admin' WHERE false",
        "CREATE TABLE pwned (id integer)",
    ],
)
def test_privileges_alone_stop_writes_even_with_readonly_mode_off(statement):
    # Two independent locks: (1) read-only transactions, (2) the role only has SELECT.
    # Here lock 1 is genuinely switched off (autocommit makes the SET take effect immediately).
    try:
        conn = psycopg.connect(SETTINGS.ro_dsn, autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    conn.execute("SET default_transaction_read_only = off")
    assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "off"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)
    conn.close()


def test_a_session_can_disable_its_own_timeout():
    # Documents a KNOWN GAP: the role's 10 s timeout is a default, not a wall. The Guard must
    # therefore reject SET statements (red-team item dos_disable_timeout) and set the timeout
    # itself on every connection it opens.
    conn = _connect()
    conn.execute("SET statement_timeout = 0")
    assert conn.execute("SHOW statement_timeout").fetchone()[0] == "0"
    conn.rollback()
    conn.close()


def test_role_has_a_statement_timeout():
    conn = _connect()
    value = conn.execute("SHOW statement_timeout").fetchone()[0]
    conn.close()
    assert value == "10s"
