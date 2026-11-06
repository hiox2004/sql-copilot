"""Unit tests for the Guard (no database needed): run the whole red-team set through it."""

import pytest

from t2sql.core.config import REPO_ROOT
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.guard import GuardViolation, guard_sql
from t2sql.validation.redteam import load_redteam

DICTIONARY = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
REDTEAM = load_redteam(REPO_ROOT / "data" / "eval" / "redteam.yaml")
TABLES = set(DICTIONARY.tables)
BLOCKED = DICTIONARY.blocked_columns()


def guard(sql: str, **kwargs):
    return guard_sql(
        sql,
        sqlglot_dialect="postgres",
        allowed_tables=TABLES,
        blocked_columns=BLOCKED,
        **kwargs,
    )


def rule_of(sql: str) -> str:
    with pytest.raises(GuardViolation) as info:
        guard(sql)
    return info.value.rule


# ---------- the red-team set ----------

STOPPED_BY_REJECTION = [i for i in REDTEAM.items if i.sql and i.blocked_by != ["guard_limits"]]
STOPPED_BY_LIMIT = [i for i in REDTEAM.items if i.sql and i.blocked_by == ["guard_limits"]]


@pytest.mark.parametrize("item", STOPPED_BY_REJECTION, ids=lambda i: i.id)
def test_attack_is_rejected(item):
    with pytest.raises(GuardViolation):
        guard(item.sql)


@pytest.mark.parametrize("item", STOPPED_BY_LIMIT, ids=lambda i: i.id)
def test_unbounded_query_is_limited(item):
    result = guard(item.sql)
    assert result.limit_added
    assert "LIMIT 1000" in result.sql


def test_every_attack_with_sql_is_covered_by_one_of_the_two_tests():
    with_sql = [i for i in REDTEAM.items if i.sql]
    assert len(STOPPED_BY_REJECTION) + len(STOPPED_BY_LIMIT) == len(with_sql)


# ---------- specific rules ----------


@pytest.mark.parametrize(
    ("sql", "rule"),
    [
        ("DROP TABLE users", "not_select"),
        ("SELECT 1; SELECT 2", "multiple_statements"),
        (
            "WITH d AS (DELETE FROM users RETURNING id) SELECT count(*) FROM d",
            "forbidden_statement",
        ),
        ("SELECT * INTO copy_of_users FROM users", "forbidden_statement"),
        ("SELECT pg_sleep(5)", "blocked_function"),
        ("SELECT PG_READ_FILE('/etc/passwd')", "blocked_function"),
        ("SELECT * FROM pg_shadow", "system_table"),
        ("SELECT * FROM information_schema.tables", "system_table"),
        ("SELECT * FROM not_a_table", "unknown_table"),
        ("SELECT email FROM users", "pii_column"),
        ("SELECT u.email FROM users u", "pii_column"),
        ("SELECT * FROM users", "pii_star"),
        ("SELECT u.* FROM users u", "pii_star"),
        ("SELECT count(*) FROM users WHERE email = 'a@b.c'", "pii_column"),
        ("SET statement_timeout = 0", "not_select"),
        ("", "multiple_statements"),
    ],
)
def test_rule_names(sql, rule):
    assert rule_of(sql) == rule


# ---------- things that must be allowed ----------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM users",
        "SELECT status, count(*) FROM subscriptions GROUP BY status",
        "SELECT o.name, s.mrr_cents FROM organizations o JOIN subscriptions s ON s.org_id = o.id",
        "WITH t AS (SELECT org_id FROM subscriptions) SELECT count(*) FROM t",
        "SELECT id FROM users UNION SELECT id FROM employees",
        "SELECT role, count(*) FROM users GROUP BY role",
        "SELECT * FROM subscriptions",
    ],
)
def test_legitimate_queries_pass(sql):
    assert guard(sql).sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT row_to_json(u) FROM users u",
        "SELECT to_jsonb(users) FROM users",
        "SELECT u FROM users u",
        "SELECT * FROM (SELECT * FROM users) q",
    ],
)
def test_whole_row_and_nested_star_leaks_are_blocked(sql):
    with pytest.raises(GuardViolation):
        guard(sql)


def test_table_valued_functions_are_allowed_but_vetted():
    ok = (
        "SELECT d::date, count(*) FROM "
        "generate_series(now() - interval '5 days', now(), interval '1 day') d GROUP BY 1"
    )
    assert guard(ok).sql
    assert rule_of("SELECT * FROM pg_ls_dir('/')") == "blocked_function"


def test_pii_in_another_table_does_not_block_a_same_named_safe_column():
    # `name` is not flagged anywhere; `email` is flagged on users but organizations has none.
    assert guard("SELECT name FROM organizations").sql


def test_pii_column_check_resolves_aliases():
    # subscriptions has no pii columns, even if the query also reads users.
    assert guard("SELECT s.status FROM subscriptions s JOIN users u ON u.org_id = s.org_id").sql


# ---------- LIMIT handling ----------


def test_missing_limit_is_added():
    result = guard("SELECT id FROM subscriptions")
    assert result.limit_added and result.sql.endswith("LIMIT 1000")


def test_small_limit_is_kept():
    result = guard("SELECT id FROM subscriptions LIMIT 5")
    assert not result.limit_added and result.sql.endswith("LIMIT 5")


def test_huge_limit_is_lowered():
    result = guard("SELECT id FROM subscriptions LIMIT 1000000")
    assert result.limit_added and result.sql.endswith("LIMIT 1000")


def test_custom_max_rows():
    assert guard("SELECT id FROM subscriptions", max_rows=10).sql.endswith("LIMIT 10")


def test_union_gets_a_limit_too():
    assert "LIMIT" in guard("SELECT id FROM users UNION SELECT id FROM employees").sql


# ---------- every metric in the dictionary is itself acceptable to the guard ----------


@pytest.mark.parametrize("name", sorted(DICTIONARY.metrics))
def test_dictionary_metrics_pass_the_guard(name):
    from datetime import UTC, datetime

    from t2sql.core.metric_render import render_metric_sql

    sql = render_metric_sql(DICTIONARY.metrics[name], datetime(2026, 11, 5, 12, tzinfo=UTC))
    assert guard(sql).sql
