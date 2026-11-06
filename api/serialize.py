"""Turn an Answer (and the values inside its rows) into plain JSON-safe Python.

Database values come back as Decimal, date, datetime and friends, which the json module cannot
write. Money in this database is a Decimal, so it becomes a float (fine for dashboards; the
database already did the cents-to-dollars division). Dates become ISO-8601 strings.
"""

import dataclasses
import math
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value  # bool before int matters: True must stay true, not 1
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Decimal):
        as_float = float(value)
        return as_float if math.isfinite(as_float) else str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in value]
    if isinstance(value, bytes):
        return value.hex()
    return str(value)  # UUID, memoryview, anything unexpected: a safe text form


def answer_to_json(answer: Any) -> dict[str, Any]:
    """Serialise a pipeline Answer dataclass to a JSON-safe dict."""
    return to_jsonable(dataclasses.asdict(answer))
