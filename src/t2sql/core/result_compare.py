"""Decide whether two query results are "the same answer" (execution accuracy).

We compare ROWS, never SQL text, because many different queries are correct. Rules:
  - column names and aliases are ignored; columns are compared by position, and the number of
    columns must match (an extra column the question did not ask for makes the answer wrong);
  - numbers match when they differ by at most 0.051 (plus a tiny relative slack for huge values),
    so 19.4 matches 19.39 (a different number of decimals is not a different answer) but 19.4 does
    not match 19.5; int 5 matches 5.0 and Decimal('5.00');
  - booleans only match booleans (in Python True == 1, which would be wrong here);
  - dates and timestamps are compared as ISO text;
  - row order is ignored unless `order_matters` (use it for "top N" style questions).
"""

from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

Row = tuple[Any, ...]

ABS_TOL = 0.051  # half a unit in the first decimal place: the largest error from rounding to 1 dp
REL_TOL = 1e-6


def normalize_value(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, int | float | Decimal):
        return float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    return value if isinstance(value, str) else str(value)


def normalize_rows(rows: Sequence[Sequence[Any]]) -> list[Row]:
    return [tuple(normalize_value(v) for v in row) for row in rows]


def _values_equal(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= ABS_TOL + REL_TOL * max(abs(a), abs(b))
    return a == b and type(a) is type(b)


def _rows_equal(a: Row, b: Row) -> bool:
    return len(a) == len(b) and all(_values_equal(x, y) for x, y in zip(a, b, strict=True))


def results_match(
    expected: Sequence[Sequence[Any]],
    actual: Sequence[Sequence[Any]],
    *,
    order_matters: bool = False,
) -> bool:
    exp_rows, act_rows = normalize_rows(expected), normalize_rows(actual)
    if len(exp_rows) != len(act_rows):
        return False
    if order_matters:
        return all(_rows_equal(e, a) for e, a in zip(exp_rows, act_rows, strict=True))
    # Unordered: pair every expected row with a distinct matching actual row.
    unused = list(act_rows)
    for row in exp_rows:
        for index, candidate in enumerate(unused):
            if _rows_equal(row, candidate):
                del unused[index]
                break
        else:
            return False
    return True
