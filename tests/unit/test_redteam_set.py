"""Shape checks on data/eval/redteam.yaml (no database needed)."""

import pytest

from t2sql.core.config import REPO_ROOT
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.redteam import RedTeamItem, load_redteam

REDTEAM = load_redteam(REPO_ROOT / "data" / "eval" / "redteam.yaml")


def test_set_covers_every_category():
    assert {item.category for item in REDTEAM.items} == {
        "write", "ddl", "privilege", "stacking", "dos", "pii", "prompt_injection"
    }  # fmt: skip


def test_every_layer_has_attacks_assigned():
    for layer in ("db_role", "guard_parser", "guard_limits", "guard_pii"):
        assert REDTEAM.blocked_by(layer), f"no attack is assigned to {layer}"


def test_pii_attacks_touch_columns_the_dictionary_blocks():
    dictionary = load_dictionary(REPO_ROOT / "data" / "dictionaries" / "saas.yaml")
    blocked_names = {column for _, column in dictionary.blocked_columns()}
    for item in REDTEAM.blocked_by("guard_pii"):
        if item.sql and "*" not in item.sql:
            assert any(name in item.sql for name in blocked_names), item.id


def test_item_needs_something_to_run():
    with pytest.raises(ValueError, match="question, an sql"):
        RedTeamItem(id="x", category="write", description="d", blocked_by=["guard_parser"])


def test_db_role_item_needs_sql():
    with pytest.raises(ValueError, match="db_role"):
        RedTeamItem(
            id="x", category="write", description="d", question="q", blocked_by=["db_role"]
        )
