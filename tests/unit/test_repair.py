import json

from t2sql.core.schema_models import ColumnInfo, SchemaInfo, TableInfo
from t2sql.generation.client import Completion
from t2sql.graph.repair import generate_with_repair
from t2sql.validation.verify import Verdict, repair_hint


def reply(sql: str) -> Completion:
    text = json.dumps({"sql": sql, "tables_used": [], "assumptions": []})
    return Completion(text, 1.0, 10, 10)


def run(replies, ok_sqls, max_retries=2):
    seen = []
    queue = list(replies)

    def ask(messages):
        seen.append(len(messages))
        return queue.pop(0)

    def verify(sql):
        return (
            Verdict(True, sql + " LIMIT 1")
            if sql in ok_sqls
            else Verdict(False, sql, 'column "x" does not exist')
        )

    return generate_with_repair(
        [{"role": "user", "content": "q"}],
        ask=ask,
        verify=verify,
        hint=lambda e, s: "hint",
        max_retries=max_retries,
    ), seen


def test_first_try_success_needs_no_retry():
    result, seen = run([reply("good")], {"good"})
    assert result.ok and result.sql == "good LIMIT 1" and len(result.attempts) == 1
    assert seen == [1]


def test_error_is_fed_back_and_second_try_wins():
    result, seen = run([reply("bad"), reply("good")], {"good"})
    assert result.ok and len(result.attempts) == 2
    assert seen == [1, 3]  # the retry sees: question, failed answer, repair message
    assert result.attempts[0].error and not result.attempts[1].error


def test_gives_up_after_max_retries():
    result, _ = run([reply("bad")] * 3, set())
    assert not result.ok and len(result.attempts) == 3 and result.sql is None


def test_non_json_reply_counts_as_a_failed_attempt():
    result, _ = run([Completion("oops", 1.0, 1, 1), reply("good")], {"good"})
    assert result.ok and result.attempts[0].sql is None


def schema():
    def t(name, *cols):
        return TableInfo(name, tuple(ColumnInfo(c, "text", False) for c in cols))

    return SchemaInfo(
        (
            t("subscriptions", "id", "org_id", "status"),
            t("users", "id", "email", "org_id"),
            t("orders", "id", "customer_id", "total_cents"),
        )
    )


def test_hint_says_where_a_name_lives_and_lists_real_columns():
    hint = repair_hint(
        'column "org_id" does not exist',
        "SELECT org_id FROM orders",
        schema(),
        sqlglot_dialect="postgres",
    )
    assert "exists in: subscriptions, users" in hint
    assert "orders columns: id, customer_id, total_cents" in hint


def test_hint_suggests_close_names_and_hides_blocked_columns():
    hint = repair_hint(
        'column "total_cent" does not exist',
        "SELECT total_cent FROM orders",
        schema(),
        sqlglot_dialect="postgres",
        blocked_columns={("users", "email")},
    )
    assert "did you mean: total_cents" in hint
    assert "email" not in repair_hint(
        'column "email" does not exist',
        "SELECT email FROM users",
        schema(),
        sqlglot_dialect="postgres",
        blocked_columns={("users", "email")},
    )


def test_hint_understands_alias_dot_column_errors():
    hint = repair_hint(
        "column t1.org_id does not exist",
        "SELECT t1.org_id FROM orders t1",
        schema(),
        sqlglot_dialect="postgres",
    )
    assert "exists in: subscriptions, users" in hint
