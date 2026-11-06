"""The generate -> verify -> repair loop (a plain bounded loop; LangGraph can wrap it later).

    ask the model -> parse JSON -> verify (Guard + EXPLAIN) -> ok? done : tell the model why, retry

Injected functions (`ask`, `verify`, `hint`) keep this file free of models and databases, so it is
tested with fakes. Retries are capped because each costs seconds on a laptop (p95 budget: 10 s).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from t2sql.generation.client import Completion, parse_model_json
from t2sql.generation.prompt import build_repair_message
from t2sql.validation.verify import Verdict

MAX_RETRIES = 2


@dataclass
class Attempt:
    sql: str | None
    error: str  # empty when the attempt passed verification
    seconds: float


@dataclass
class RepairResult:
    ok: bool
    sql: str | None  # guarded SQL when ok
    data: dict[str, Any] | None  # parsed model reply of the last attempt
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return sum(a.seconds for a in self.attempts)


def generate_with_repair(
    messages: list[dict[str, str]],
    *,
    ask: Callable[[list[dict[str, str]]], Completion],
    verify: Callable[[str], Verdict],
    hint: Callable[[str, str], str],
    max_retries: int = MAX_RETRIES,
) -> RepairResult:
    history = list(messages)
    result = RepairResult(ok=False, sql=None, data=None)
    for _ in range(max_retries + 1):
        reply = ask(history)
        data = parse_model_json(reply.text)
        if data is None:
            error, sql = "the reply was not the required JSON object with an sql string", None
        else:
            sql = data["sql"]
            verdict = verify(sql)
            if verdict.ok:
                result.attempts.append(Attempt(sql, "", reply.seconds))
                result.ok, result.sql, result.data = True, verdict.sql, data
                return result
            error = verdict.error
        result.attempts.append(Attempt(sql, error, reply.seconds))
        result.data = data
        history.append({"role": "assistant", "content": reply.text})
        history.append(build_repair_message(error, hint(error, sql or "")))
    return result
