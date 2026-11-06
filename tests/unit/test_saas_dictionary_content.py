"""Checks on the real data/dictionaries/saas.yaml that need no database."""

import re
from datetime import UTC, datetime

import pytest

from t2sql.core.config import REPO_ROOT
from t2sql.core.metric_render import render_metric_sql, today_literal
from t2sql.core.profile import load_profile
from t2sql.retrieval.dictionary import load_dictionary

PROFILE = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
DICTIONARY = load_dictionary(REPO_ROOT / PROFILE.dictionary)
TODAY = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def test_profile_and_dictionary_agree():
    assert DICTIONARY.meta.id == PROFILE.id
    assert DICTIONARY.meta.dialect == PROFILE.dialect


def test_no_todo_left_from_the_draft():
    text = (REPO_ROOT / PROFILE.dictionary).read_text(encoding="utf-8")
    assert "TODO" not in text


def test_no_personal_data_pasted_into_the_dictionary():
    text = (REPO_ROOT / PROFILE.dictionary).read_text(encoding="utf-8")
    assert not re.search(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", text), "looks like an email address"


def test_pii_columns_are_the_ones_we_decided():
    assert DICTIONARY.blocked_columns() == frozenset(
        {
            ("addresses", "postal_code"),
            ("employees", "email"),
            ("employees", "full_name"),
            ("employees", "salary_cents"),
            ("leads", "contact_email"),
            ("sales_reps", "full_name"),
            ("support_agents", "full_name"),
            ("support_tickets", "subject"),
            ("ticket_comments", "body"),
            ("users", "email"),
            ("users", "full_name"),
        }
    )


def test_agreed_business_metrics_exist():
    assert {"mrr", "active_customers", "churned_customers", "revenue_total", "open_tickets"} <= set(
        DICTIONARY.metrics
    )


# ---------- metric rendering ----------


def test_today_literal_is_utc_timestamptz():
    assert today_literal(TODAY) == "TIMESTAMPTZ '2026-11-05 12:00:00+00'"


def test_today_literal_converts_other_timezones_to_utc():
    from datetime import timedelta, timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    assert today_literal(datetime(2026, 11, 5, 17, 30, tzinfo=ist)) == today_literal(TODAY)


def test_today_literal_requires_a_timezone():
    with pytest.raises(ValueError, match="timezone"):
        today_literal(datetime(2026, 11, 5, 12, 0))


def test_render_fills_today_and_default_parameter():
    sql = render_metric_sql(DICTIONARY.metrics["churned_customers"], TODAY)
    assert "TIMESTAMPTZ '2026-11-05 12:00:00+00'" in sql
    assert "make_interval(days => 30)" in sql
    assert "{" not in sql


def test_render_overrides_a_parameter():
    sql = render_metric_sql(DICTIONARY.metrics["churned_customers"], TODAY, window_days=14)
    assert "make_interval(days => 14)" in sql


def test_render_rejects_unknown_parameter():
    with pytest.raises(ValueError, match="unknown parameter"):
        render_metric_sql(DICTIONARY.metrics["churned_customers"], TODAY, days=1)


def test_render_rejects_non_integer_parameter():
    with pytest.raises(ValueError, match="integer"):
        render_metric_sql(
            DICTIONARY.metrics["churned_customers"], TODAY, window_days="1; DROP TABLE x"
        )
