"""The golden set is only trustworthy if every answer is verified by execution.

Each golden SQL must pass the Guard, run as the READ-ONLY role, give the same rows twice, and return
a small, non-empty, non-NULL answer. The set as a whole must be varied enough to be a fair test.
"""

from collections import Counter

import psycopg
import pytest

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.result_compare import results_match
from t2sql.dialects import get_dialect
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.executor import run_guarded
from t2sql.validation.golden import load_all_golden
from t2sql.validation.guard import guard_sql

pytestmark = pytest.mark.integration

SETTINGS = Settings.from_env()
DICTIONARY = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
GOLDEN = load_all_golden(REPO_ROOT / "data" / "eval" / "golden")
GUARD = {
    "dialect": get_dialect("postgres"),
    "allowed_tables": set(DICTIONARY.tables),
    "blocked_columns": DICTIONARY.blocked_columns(),
}
MAX_ANSWER_ROWS = 100


@pytest.fixture(scope="module")
def conn():
    try:
        connection = psycopg.connect(SETTINGS.ro_dsn)
    except psycopg.OperationalError as exc:
        pytest.skip(f"database not reachable: {exc}")
    yield connection
    connection.close()


@pytest.mark.parametrize("item", GOLDEN, ids=lambda i: i.id)
def test_golden_item_is_verified_by_execution(conn, item):
    sql = guard_sql(item.sql, **GUARD).sql
    first, second = run_guarded(conn, sql), run_guarded(conn, sql)
    assert first.rows == second.rows, "not deterministic"
    assert len(first.rows) <= MAX_ANSWER_ROWS
    if item.expect_empty:
        assert not first.rows
    else:
        assert first.rows, "empty answer"
        assert any(v is not None for row in first.rows for v in row), "only NULLs"
    assert results_match(first.rows, second.rows, order_matters=item.order_matters)


def test_set_is_large_and_varied_enough():
    assert len(GOLDEN) >= 50
    difficulty = Counter(i.difficulty for i in GOLDEN)
    assert all(difficulty[d] >= 10 for d in ("easy", "medium", "hard")), difficulty
    # paraphrases share a template, so there are fewer templates than items
    assert len({i.template for i in GOLDEN}) < len(GOLDEN)


def test_key_tables_are_exercised():
    used = " ".join(i.sql.lower() for i in GOLDEN)
    for table in ("subscriptions", "payments", "support_tickets", "login_events", "opportunities"):
        assert table in used, f"no golden query touches {table}"


def test_no_golden_question_leaks_sql_or_column_names():
    for item in GOLDEN:
        assert "_cents" not in item.question and "select " not in item.question.lower(), item.id


def test_templates_do_not_straddle_domains():
    domains: dict[str, set[str]] = {}
    for item in GOLDEN:
        domains.setdefault(item.template, set()).add(item.id.rsplit("_", 1)[0])
    assert all(len(d) == 1 for d in domains.values())
