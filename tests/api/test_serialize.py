"""The JSON helper that turns database values into plain JSON types (no database needed)."""

import dataclasses
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from api.serialize import answer_to_json, to_jsonable

from t2sql.graph.pipeline import Answer


def test_scalars_keep_their_json_type():
    assert to_jsonable(None) is None
    assert to_jsonable(True) is True  # bool must not turn into 1
    assert to_jsonable(False) is False
    assert to_jsonable(7) == 7
    assert to_jsonable("text") == "text"
    assert to_jsonable(1.5) == 1.5


def test_decimal_becomes_float():
    assert to_jsonable(Decimal("1234.50")) == 1234.5
    assert isinstance(to_jsonable(Decimal("0.10")), float)


def test_non_finite_numbers_become_text():
    assert to_jsonable(Decimal("NaN")) == "NaN"
    assert to_jsonable(float("inf")) == "inf"


def test_dates_and_times_become_iso_strings():
    assert to_jsonable(date(2026, 11, 5)) == "2026-11-05"
    assert to_jsonable(datetime(2026, 11, 5, 12, 0, tzinfo=UTC)) == "2026-11-05T12:00:00+00:00"
    assert to_jsonable(time(9, 30)) == "09:30:00"


def test_containers_are_converted_recursively():
    value = {"a": [Decimal("2.5"), None], "b": (date(2026, 1, 2),)}
    assert to_jsonable(value) == {"a": [2.5, None], "b": ["2026-01-02"]}


def test_unknown_types_fall_back_to_text_and_bytes_to_hex():
    assert to_jsonable(timedelta(days=1)) == "1 day, 0:00:00"
    assert to_jsonable(b"\x01\xff") == "01ff"


def test_answer_serialises_to_json_text():
    answer = Answer(
        ok=True,
        question="q",
        sql="SELECT 1",
        columns=["total"],
        rows=[[Decimal("9.99"), date(2026, 11, 5), None]],
    )
    payload = answer_to_json(answer)
    assert payload["rows"] == [[9.99, "2026-11-05", None]]
    assert payload["attempts"] == 0
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload) == {f.name for f in dataclasses.fields(Answer)}
