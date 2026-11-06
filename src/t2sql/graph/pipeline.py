"""The whole copilot for one question: context -> generate -> verify/repair -> guarded run.

This is the single entry point the API calls (and the benchmark can reuse). It knows nothing about
HTTP. The model call is injected as `ask` so tests can feed it attack SQL without a model.

Safety order is fixed: model SQL is never executed unless `verify_sql` (Guard + EXPLAIN) approved
it, and then only through `run_guarded` (read-only transaction, our own timeout).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from t2sql.core.dictionary_models import Dictionary
from t2sql.core.schema_models import SchemaInfo
from t2sql.dialects.base import Dialect
from t2sql.generation.client import Completion
from t2sql.generation.prompt import build_messages
from t2sql.graph.repair import MAX_RETRIES, generate_with_repair
from t2sql.retrieval.context import render_context
from t2sql.validation.executor import QueryTimeout, run_guarded
from t2sql.validation.verify import repair_hint, verify_sql

MAX_ANSWER_ROWS = 200  # rows returned to the caller; the query itself is already LIMIT-capped


@dataclass
class Answer:
    ok: bool
    question: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    tables_used: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    attempts: int = 0
    seconds: float = 0.0
    error: str | None = None  # short, safe to show to the user


def answer_question(
    question: str,
    *,
    conn: "psycopg.Connection",
    schema: SchemaInfo,
    dictionary: Dictionary,
    dialect: Dialect,
    today: datetime,
    ask: Callable[[list[dict[str, str]]], Completion],
    max_retries: int = MAX_RETRIES,
) -> Answer:
    context = render_context(schema, dictionary, today)
    blocked = dictionary.blocked_columns()
    outcome = generate_with_repair(
        build_messages(question, context, today),
        ask=ask,
        verify=lambda sql: verify_sql(
            conn,
            sql,
            dialect=dialect,
            allowed_tables=set(dictionary.tables),
            blocked_columns=blocked,
        ),
        hint=lambda error, sql: repair_hint(
            error,
            sql,
            schema,
            sqlglot_dialect=dialect.sqlglot_name,
            blocked_columns=blocked,
        ),
        max_retries=max_retries,
    )
    answer = Answer(
        ok=False,
        question=question,
        attempts=len(outcome.attempts),
        seconds=round(outcome.seconds, 2),
    )
    data = outcome.data or {}
    answer.tables_used = [str(t) for t in data.get("tables_used", [])][:8]
    answer.assumptions = [str(a) for a in data.get("assumptions", [])][:3]
    if not outcome.ok or outcome.sql is None:
        last = outcome.attempts[-1].error if outcome.attempts else "no answer"
        answer.error = f"Could not produce a safe, valid query: {last}"
        return answer
    try:
        result = run_guarded(conn, outcome.sql)
    except QueryTimeout:
        answer.sql, answer.error = outcome.sql, "The query took too long and was cancelled."
        return answer
    except psycopg.Error as exc:
        conn.rollback()
        answer.sql = outcome.sql
        answer.error = f"The database rejected the query: {str(exc).strip().splitlines()[0][:150]}"
        return answer
    answer.ok, answer.sql = True, outcome.sql
    answer.columns = list(result.columns)
    answer.rows = [list(r) for r in result.rows[:MAX_ANSWER_ROWS]]
    answer.truncated = len(result.rows) > MAX_ANSWER_ROWS
    return answer
