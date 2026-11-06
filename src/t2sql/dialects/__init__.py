"""Dialect registry: look an adapter up by the name a profile gives."""

from t2sql.dialects.base import Dialect
from t2sql.dialects.postgres import PostgresDialect

_REGISTRY: dict[str, Dialect] = {PostgresDialect.name: PostgresDialect()}


def get_dialect(name: str) -> Dialect:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(f"unknown dialect {name!r}; known dialects: {known}") from None


__all__ = ["Dialect", "get_dialect"]
