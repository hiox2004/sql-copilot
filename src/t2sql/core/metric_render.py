"""Turn a dictionary metric into runnable SQL by filling in `{today}` and its parameters.

The dictionary stores metrics as templates. The model prompt and the tests both need the real SQL,
so there is exactly one function that does the substitution.
"""

from datetime import UTC, datetime

from t2sql.core.dictionary_models import Metric


def today_literal(today: datetime) -> str:
    """The pinned date as a SQL timestamptz literal, always in UTC."""
    if today.tzinfo is None:
        raise ValueError("today must include a timezone")
    utc = today.astimezone(UTC)
    return f"TIMESTAMPTZ '{utc.strftime('%Y-%m-%d %H:%M:%S')}+00'"


def render_metric_sql(metric: Metric, today: datetime, **overrides: int) -> str:
    """Return the metric's SQL with `{today}` and every parameter replaced.

    `overrides` replaces a parameter's default (for example window_days=14). Only declared
    parameters may be overridden, and values must be integers, so nothing free-form is ever pasted
    into SQL.
    """
    unknown = set(overrides) - set(metric.parameters)
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    values: dict[str, str] = {"today": today_literal(today)}
    for name, param in metric.parameters.items():
        value = overrides.get(name, param.default)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"parameter {name!r} must be an integer, got {value!r}")
        values[name] = str(value)
    return metric.sql.format(**values)
