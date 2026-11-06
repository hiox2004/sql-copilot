"""Unit tests for the pieces around introspection that need no database."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from t2sql.core.config import DEFAULT_REF_NOW, REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.core.schema_models import ColumnInfo, ForeignKey, SchemaInfo, TableInfo
from t2sql.dialects import get_dialect
from t2sql.dialects.postgres.introspect import parse_enum_check
from t2sql.retrieval.dictionary import parse_dictionary
from t2sql.retrieval.draft_dictionary import (
    draft_dictionary_yaml,
    is_money_column,
    looks_like_pii,
)

# ---------- CHECK constraint parsing ----------


def test_enum_check_is_parsed():
    definition = "CHECK ((status = ANY (ARRAY['open'::text, 'pending'::text, 'closed'::text])))"
    assert parse_enum_check(definition) == ("status", ("open", "pending", "closed"))


def test_enum_check_keeps_an_embedded_quote():
    definition = "CHECK ((kind = ANY (ARRAY['it''s'::text, 'b'::text])))"
    assert parse_enum_check(definition) == ("kind", ("it's", "b"))


@pytest.mark.parametrize(
    "definition",
    [
        "CHECK ((mrr_cents >= 0))",  # a range, not a list of values
        "CHECK (((status = 'canceled'::text) = (canceled_at IS NOT NULL)))",  # cross-column rule
        "CHECK (((score >= 1) AND (score <= 5)))",
    ],
)
def test_non_enum_checks_are_ignored(definition):
    assert parse_enum_check(definition) is None


# ---------- config ----------


def test_config_default_matches_the_database_loader_script():
    # Two places define the pinned "today". This test stops them drifting apart.
    script = (REPO_ROOT / "infra" / "postgres" / "init" / "02_load_schema.sh").read_text(
        encoding="utf-8"
    )
    match = re.search(r'REF_NOW="\$\{REF_NOW:-([^}]+)\}"', script)
    assert match is not None, "could not find the REF_NOW default in 02_load_schema.sh"
    assert match.group(1) == DEFAULT_REF_NOW


def test_settings_defaults_and_pinned_date(monkeypatch):
    monkeypatch.delenv("REF_NOW", raising=False)
    monkeypatch.delenv("DB_HOST", raising=False)
    settings = Settings.from_env(env_file=None)
    assert settings.ref_now == datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
    assert settings.db_host == "127.0.0.1"


def test_settings_reject_a_date_without_timezone(monkeypatch):
    monkeypatch.setenv("REF_NOW", "2026-11-05 12:00:00")
    with pytest.raises(ValueError, match="timezone"):
        Settings.from_env(env_file=None)


def test_dsn_quotes_awkward_passwords(monkeypatch):
    monkeypatch.setenv("COPILOT_RO_PASSWORD", "pa ss'word")
    dsn = Settings.from_env(env_file=None).ro_dsn
    assert "password='pa ss\\'word'" in dsn


# ---------- profile and dialect registry ----------


def test_saas_profile_loads():
    profile = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
    assert (profile.id, profile.dialect, profile.schema_name) == ("saas", "postgres", "public")


def test_profile_rejects_unknown_fields(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: x\ndialect: postgres\nschema_name: public\ndictionary: d.yaml\nzzz: 1\n")
    with pytest.raises(ValueError, match="zzz"):
        load_profile(bad)


def test_unknown_dialect_lists_the_known_ones():
    with pytest.raises(ValueError, match="known dialects"):
        get_dialect("nosuchdb")


def test_postgres_explain_never_analyzes():
    sql = get_dialect("postgres").explain_statement("SELECT 1")
    assert sql == "EXPLAIN SELECT 1"
    assert "ANALYZE" not in sql.upper()


# ---------- draft dictionary ----------

SCHEMA = SchemaInfo(
    tables=(
        TableInfo(
            name="users",
            columns=(
                ColumnInfo("id", "bigint", False),
                ColumnInfo("email", "text", False),
                ColumnInfo("role", "text", False, ("admin", "on")),  # "on" must stay a string
                ColumnInfo("mrr_cents", "integer", False),
            ),
            primary_key=("id",),
        ),
        TableInfo(
            name="orders",
            columns=(ColumnInfo("id", "bigint", False), ColumnInfo("user_id", "bigint", False)),
            primary_key=("id",),
            foreign_keys=(ForeignKey(("user_id",), "users", ("id",)),),
        ),
    )
)


def test_draft_is_loadable_by_the_real_loader():
    d = parse_dictionary(draft_dictionary_yaml(SCHEMA, "demo", "postgres"))
    assert set(d.tables) == {"users", "orders"}
    assert d.tables["users"].columns["role"].values["on"] == "TODO"
    assert d.tables["users"].columns["mrr_cents"].unit == "cents"
    assert d.blocked_columns() == frozenset({("users", "email")})


def test_draft_leaves_plain_columns_out():
    d = parse_dictionary(draft_dictionary_yaml(SCHEMA, "demo", "postgres"))
    assert "id" not in d.tables["users"].columns
    assert d.tables["orders"].columns == {}


@pytest.mark.parametrize("name", ["email", "contact_email", "full_name", "postal_code", "ip"])
def test_pii_heuristic_flags(name):
    assert looks_like_pii(name)


def test_pii_heuristic_flags_salary():
    assert looks_like_pii("salary_cents")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("amount_cents", True),
        ("mrr_cents_before", True),
        ("cents_per_unit", False),
        ("percent_off", False),
    ],
)
def test_money_column_detection(name, expected):
    assert is_money_column(name) is expected


@pytest.mark.parametrize("name", ["status", "trip_id", "description", "ship_date"])
def test_pii_heuristic_does_not_flag_lookalikes(name):
    assert not looks_like_pii(name)
