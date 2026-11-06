"""Unit tests for the dictionary models and loader (no database needed).

Pattern: start from one valid fixture, change exactly ONE thing, and check that loading fails with
a message that names the offending field. `mutate` asserts the change really applied, so a test can
never "pass" by accidentally testing nothing.
"""

from pathlib import Path

import pytest

from t2sql.retrieval.dictionary import DictionaryError, load_dictionary, parse_dictionary

FIXTURE = Path(__file__).parent / "fixtures" / "dictionary_valid.yaml"
VALID = FIXTURE.read_text(encoding="utf-8")


def mutate(text: str, old: str, new: str) -> str:
    assert old in text, f"test bug: {old!r} not found in fixture"
    return text.replace(old, new, 1)


def fails_with(text: str, *fragments: str) -> str:
    with pytest.raises(DictionaryError) as info:
        parse_dictionary(text, source="test.yaml")
    message = str(info.value)
    for fragment in fragments:
        assert fragment in message, f"expected {fragment!r} in:\n{message}"
    return message


# ---------- the happy path ----------


def test_valid_fixture_loads():
    d = load_dictionary(FIXTURE)
    assert d.meta.id == "demo"
    assert set(d.tables) == {"organizations", "subscriptions", "users"}
    assert d.tables["subscriptions"].columns["mrr_cents"].unit == "cents"
    assert d.metrics["churned_customers"].parameters["window_days"].default == 30
    assert d.terms["big account"].maps_to == "subscriptions"
    assert [r.id for r in d.global_rules] == ["money_in_cents", "use_today"]


def test_blocked_columns_lists_pii_only():
    d = parse_dictionary(VALID)
    assert d.blocked_columns() == frozenset({("users", "email")})


def test_loaded_dictionary_is_immutable():
    d = parse_dictionary(VALID)
    with pytest.raises(Exception, match="frozen"):
        d.meta.id = "other"


# ---------- typos and unknown fields ----------


def test_unknown_field_is_rejected_with_its_path():
    text = mutate(VALID, "synonyms: [clients, accounts]", "synonymns: [clients, accounts]")
    fails_with(text, "tables.organizations.synonymns", "Extra inputs are not permitted")


def test_identifier_must_be_snake_case():
    text = mutate(VALID, "  organizations:\n    description", "  Organizations:\n    description")
    fails_with(text, "tables.Organizations")


def test_description_length_is_capped():
    text = mutate(VALID, '"Customer companies (accounts)."', '"' + "x" * 201 + '"')
    fails_with(text, "tables.organizations.description", "at most 200")


# ---------- metrics ----------


def test_metric_requires_an_owner():
    owner_line = "    owner: meherlktalluri\n    rationale: \"Trialing"
    text = mutate(VALID, owner_line, "    rationale: \"Trialing")
    fails_with(text, "metrics.mrr.owner", "Field required")


def test_metric_unknown_placeholder_is_rejected():
    text = mutate(VALID, "{today} - {window_days}", "{yesterday} - {window_days}")
    fails_with(text, "metrics.churned_customers", "unknown placeholder", "yesterday")


def test_metric_declared_but_unused_parameter_is_rejected():
    text = mutate(VALID, "{today} - {window_days}", "{today}")
    fails_with(text, "metrics.churned_customers", "never used", "window_days")


def test_metric_must_be_select_or_with():
    text = mutate(VALID, '"SELECT SUM(mrr_cents)', '"DELETE FROM x -- SELECT SUM(mrr_cents)')
    fails_with(text, "metrics.mrr", "must start with SELECT or WITH")


def test_metric_must_be_one_statement():
    text = mutate(VALID, "'past_due')\"", "'past_due'); SELECT 1\"")
    fails_with(text, "metrics.mrr", "single statement")


def test_metric_sql_with_unbalanced_braces_is_rejected():
    old = "status IN ('active', 'past_due')\""
    text = mutate(VALID, old, "status IN ('active', 'past_due') {\"")
    fails_with(text, "metrics.mrr", "malformed braces")


# ---------- cross-references and rules ----------


def test_term_must_point_at_a_declared_table():
    text = mutate(VALID, "maps_to: organizations", "maps_to: companies")
    fails_with(text, "companies", "unknown table")


def test_synonym_cannot_belong_to_two_tables():
    text = mutate(VALID, "synonyms: [contracts]", "synonyms: [clients]")
    fails_with(text, "'clients' is claimed by both")


def test_global_rule_ids_must_be_unique():
    text = mutate(VALID, "id: use_today", "id: money_in_cents")
    fails_with(text, "global_rules ids must be unique")


def test_pii_column_cannot_list_values():
    old = "email:\n        pii: true"
    text = mutate(VALID, old, old + "\n        values: {a: b}")
    fails_with(text, "tables.users.columns.email", "pii column must not list values")


def test_independent_structural_problems_are_reported_together():
    text = mutate(VALID, "synonyms: [clients, accounts]", "synonymns: [clients]")
    text = mutate(text, '"Customer companies (accounts)."', '"' + "x" * 201 + '"')
    message = fails_with(text, "2 problem(s)")
    assert "synonymns" in message and "tables.organizations.description" in message


def test_cross_reference_checks_only_run_once_the_structure_is_valid():
    # Pydantic "after" validators (our cross-reference rules) are skipped while field errors exist.
    # So a typo hides a bad maps_to until the typo is fixed. Known, accepted behaviour.
    text = mutate(VALID, "synonyms: [clients, accounts]", "synonymns: [clients]")
    text = mutate(text, "maps_to: organizations", "maps_to: companies")
    message = fails_with(text, "1 problem(s)", "synonymns")
    assert "companies" not in message


# ---------- the two YAML traps ----------


def test_duplicate_yaml_keys_are_rejected():
    text = VALID + "\nmetrics:\n  mrr:\n    description: duplicate top-level key\n"
    fails_with(text, "duplicate key 'metrics'", "line")


def test_unquoted_on_off_are_rejected_not_silently_turned_into_booleans():
    # YAML 1.1 reads unquoted on/off as True/False. Strict strings must catch it.
    text = mutate(VALID, '"on": "send', 'on: "send')
    text = mutate(text, '"off": "do not', 'off: "do not')
    fails_with(
        text,
        "tables.users.columns.invoice_emails",
        "put on/off/yes/no/true/false in quotes",
    )


def test_quoted_on_off_are_accepted_as_strings():
    d = parse_dictionary(VALID)
    assert set(d.tables["users"].columns["invoice_emails"].values) == {"on", "off"}


# ---------- file-level problems ----------


@pytest.mark.parametrize("text", ["", "- just\n- a list\n", "42"])
def test_top_level_must_be_a_mapping(text):
    fails_with(text, "top level must be a mapping")


def test_invalid_yaml_syntax_is_reported():
    fails_with("meta: [unclosed", "invalid YAML")


def test_missing_file_gives_a_readable_error(tmp_path):
    with pytest.raises(DictionaryError, match="cannot read file"):
        load_dictionary(tmp_path / "nope.yaml")
