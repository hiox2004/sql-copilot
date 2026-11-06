"""Unit tests for result comparison, golden-file format, prompt, context and reply parsing."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from t2sql.core.config import REPO_ROOT
from t2sql.core.result_compare import results_match
from t2sql.generation.client import parse_model_json
from t2sql.generation.prompt import build_messages
from t2sql.retrieval.context import render_tables
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.golden import GoldenFile, GoldenItem

TODAY = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)

# ---------- result comparison ----------


def test_numbers_match_across_types_and_rounding():
    assert results_match([(Decimal("5.00"),)], [(5,)])
    assert results_match([(0.4567,)], [(0.46,)])
    assert not results_match([(5,)], [(6,)])


def test_rounding_differences_are_tolerated_but_real_differences_are_not():
    assert results_match([(19.39,)], [(19.4,)])  # the model rounded to 1 decimal
    assert results_match([(19.4,)], [(19.39,)])
    assert not results_match([(19.39,)], [(19.5,)])
    assert not results_match([(100,)], [(101,)])  # whole numbers must be exact
    assert results_match([(126486.0,)], [(Decimal("126486.000000000000"),)])


def test_percent_and_fraction_are_different_answers():
    assert not results_match([(19.4,)], [(0.194,)])


def test_unordered_matching_pairs_rows_one_to_one():
    assert results_match([(1.0,), (1.04,)], [(1.04,), (1.0,)])
    assert not results_match([(1.0,), (1.0,)], [(1.0,), (2.0,)])


def test_row_order_is_ignored_unless_it_matters():
    a, b = [(1, "x"), (2, "y")], [(2, "y"), (1, "x")]
    assert results_match(a, b)
    assert not results_match(a, b, order_matters=True)


def test_duplicates_count():
    assert not results_match([(1,), (1,)], [(1,)])
    assert results_match([(1,), (1,)], [(1,), (1,)])


def test_column_count_and_values_must_agree():
    assert not results_match([(1, 2)], [(1,)])
    assert not results_match([(1, 2)], [(2, 3)])


def test_booleans_are_not_numbers_and_dates_compare_as_text():
    assert not results_match([(True,)], [(1,)])
    assert results_match([(date(2026, 11, 5),)], [("2026-11-05",)])


def test_none_matches_only_none():
    assert results_match([(None,)], [(None,)])
    assert not results_match([(None,)], [(0,)])


def test_empty_results():
    assert results_match([], [])
    assert not results_match([], [(1,)])


# ---------- golden file format ----------


def item(**overrides):
    base = {
        "id": "x_01",
        "template": "x_01",
        "question": "How many customers are there?",
        "sql": "SELECT count(*) FROM organizations",
        "difficulty": "easy",
    }
    return {**base, **overrides}


def test_golden_item_accepts_a_valid_item():
    assert GoldenItem(**item()).order_matters is False


@pytest.mark.parametrize(
    "overrides",
    [{"difficulty": "trivial"}, {"id": "Bad Id"}, {"question": "short"}, {"extra": 1}],
)
def test_golden_item_rejects_bad_fields(overrides):
    with pytest.raises(ValueError):
        GoldenItem(**item(**overrides))


def test_golden_file_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="duplicate"):
        GoldenFile(domain="x", items=[item(), item()])


# ---------- prompt, context, reply parsing ----------


def test_prompt_states_the_pinned_date_and_the_question():
    system, user = build_messages("How many customers?", "CTX", TODAY)
    assert "2026-11-05 12:00 UTC" in system["content"]
    assert "TIMESTAMPTZ '2026-11-05 12:00:00+00'" in system["content"]
    assert user["content"].endswith("How many customers?") and "CTX" in user["content"]


def test_prompt_requires_a_timezone():
    with pytest.raises(ValueError, match="timezone"):
        build_messages("q", "c", datetime(2026, 11, 5, 12, 0))


def test_context_never_shows_personal_data_columns():
    from t2sql.core.schema_models import ColumnInfo, SchemaInfo, TableInfo

    dictionary = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
    schema = SchemaInfo(
        tables=(
            TableInfo(
                "users",
                (ColumnInfo("id", "integer", False), ColumnInfo("email", "text", False)),
            ),
        )
    )
    text = render_tables(schema, dictionary)
    assert "TABLE users(id integer)" in text and "email" not in text


def test_context_can_be_limited_to_chosen_tables():
    from t2sql.core.schema_models import ColumnInfo, SchemaInfo, TableInfo

    dictionary = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
    cols = (ColumnInfo("id", "integer", False),)
    schema = SchemaInfo(tables=(TableInfo("users", cols), TableInfo("orders", cols)))
    text = render_tables(schema, dictionary, {"orders"})
    assert "TABLE orders" in text and "TABLE users" not in text


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ('{"sql": "SELECT 1", "tables_used": [], "assumptions": []}', True),
        ('{"tables_used": []}', False),
        ('{"sql": 5}', False),
        ("not json", False),
        ("[1, 2]", False),
    ],
)
def test_parse_model_json(text, ok):
    assert (parse_model_json(text) is not None) is ok


def test_dev_test_split_is_frozen_and_keeps_paraphrases_together():
    from pathlib import Path

    from t2sql.validation.golden import load_all_golden
    from t2sql.validation.splits import split_of

    items = load_all_golden(Path(__file__).resolve().parents[2] / "data" / "eval" / "golden")
    sides: dict[str, set[str]] = {}
    for item in items:
        sides.setdefault(item.template, set()).add(split_of(item.template))
    assert all(len(s) == 1 for s in sides.values())
    test_templates = sorted(t for t in sides if split_of(t) == "test")
    # Frozen on 2026-11-07. If this fails, someone changed the split rule or renamed a template.
    assert len(test_templates) == 14 and len(sides) - len(test_templates) == 26


def test_columns_may_come_in_any_order():
    assert results_match([("a", 1), ("b", 2)], [(1, "a"), (2, "b")])
    assert not results_match([("a", 1)], [(1, "b")])
    assert results_match([], [])
