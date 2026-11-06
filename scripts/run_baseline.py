"""Measure the model on the golden queries: execution accuracy, latency, and where it fails.

Usage (database up, model server running, golden files present):
    python scripts/run_baseline.py --mode all       # whole schema in the prompt (no retrieval)
    python scripts/run_baseline.py --mode oracle    # only the tables the golden SQL uses
                                                    # (what perfect retrieval would give)
Options: --repair (verify + up to 2 repair retries), --split dev|test|all, --limit N,
--out FILE, --label TEXT, --max-tokens N.
Writes eval/results/<label>.json and prints a summary.

Funnel per question: JSON valid -> Guard passes -> executes -> rows match the golden answer.
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime

import psycopg

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.core.result_compare import results_match
from t2sql.dialects import get_dialect
from t2sql.generation.client import ModelServerError, chat
from t2sql.generation.prompt import PROMPT_VERSION, build_messages
from t2sql.graph.repair import MAX_RETRIES, generate_with_repair
from t2sql.retrieval.context import render_context
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.executor import QueryTimeout, run_guarded
from t2sql.validation.golden import load_all_golden
from t2sql.validation.guard import guard_sql
from t2sql.validation.splits import split_of
from t2sql.validation.verify import repair_hint, tables_in_sql, verify_sql


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["all", "oracle"], default="all")
    parser.add_argument(
        "--split",
        choices=["dev", "test", "all"],
        default="all",
        help="dev for tuning; test only for final numbers (see t2sql.validation.splits)",
    )
    parser.add_argument("--repair", action="store_true", help="verify + repair retries")
    parser.add_argument("--retries", type=int, default=MAX_RETRIES, help="max repair retries")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--label", default="")
    parser.add_argument("--max-tokens", type=int, default=512)
    args = parser.parse_args()
    label = args.label or f"baseline_{args.mode}"

    settings = Settings.from_env()
    profile = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
    dictionary = load_dictionary(REPO_ROOT / profile.dictionary)
    dialect = get_dialect(profile.dialect)
    golden = load_all_golden(REPO_ROOT / "data" / "eval" / "golden")
    if args.split != "all":
        golden = [g for g in golden if split_of(g.template) == args.split]
    if args.limit:
        golden = golden[: args.limit]
    known = set(dictionary.tables)
    guard_kwargs = {
        "dialect": dialect,
        "allowed_tables": known,
        "blocked_columns": dictionary.blocked_columns(),
    }

    verify_kwargs = {
        "dialect": dialect,
        "allowed_tables": known,
        "blocked_columns": dictionary.blocked_columns(),
    }
    records = []
    with psycopg.connect(settings.ro_dsn) as conn:
        schema = dialect.introspect(conn, profile.schema_name)
        for n, item in enumerate(golden, 1):
            expected = run_guarded(conn, guard_sql(item.sql, **guard_kwargs).sql).rows
            tables = None
            if args.mode == "oracle":
                tables = set(tables_in_sql(item.sql, dialect.sqlglot_name, known))
            context = render_context(schema, dictionary, settings.ref_now, tables)
            record = {"id": item.id, "difficulty": item.difficulty, "template": item.template}
            messages = build_messages(item.question, context, settings.ref_now)
            replies = []

            def ask(msgs, replies=replies):
                reply = chat(settings.llm_base_url, msgs, max_tokens=args.max_tokens)
                replies.append(reply)
                return reply

            def verify(sql):
                return verify_sql(conn, sql, **verify_kwargs)

            def hint(error, sql):
                return repair_hint(
                    error,
                    sql,
                    schema,
                    sqlglot_dialect=dialect.sqlglot_name,
                    blocked_columns=dictionary.blocked_columns(),
                )

            try:
                outcome = generate_with_repair(
                    messages,
                    ask=ask,
                    verify=verify,
                    hint=hint,
                    max_retries=args.retries if args.repair else 0,
                )
            except ModelServerError as exc:
                print(f"model server problem: {exc}", file=sys.stderr)
                return 1
            seconds = outcome.seconds
            record.update(
                seconds=round(seconds, 2),
                prompt_tokens=replies[0].prompt_tokens,
                attempts=len(outcome.attempts),
            )
            data = outcome.data
            record["json_ok"] = data is not None
            record["stage"] = "json"
            if data is not None:
                record["sql"] = outcome.attempts[-1].sql
                if outcome.ok:
                    record["guard_ok"] = True
                    record["stage"] = "guard"
                    try:
                        actual = run_guarded(conn, outcome.sql)
                        record["exec_ok"] = True
                        record["stage"] = "exec"
                        record["match"] = results_match(
                            expected, actual.rows, order_matters=item.order_matters
                        )
                        record["stage"] = "match" if record["match"] else "wrong_rows"
                    except QueryTimeout:
                        record["error"] = "timeout"
                    except psycopg.Error as exc:
                        conn.rollback()
                        record["error"] = str(exc).strip().splitlines()[0][:150]
                else:
                    record["guard_ok"] = False
                    record["error"] = "verify:" + outcome.attempts[-1].error[:150]
            else:
                record["raw"] = replies[-1].text[:200]
            record["first_try_ok"] = outcome.attempts[0].error == "" if outcome.attempts else False
            records.append(record)
            flag = "MATCH" if record.get("match") else record["stage"]
            print(f"[{n}/{len(golden)}] {item.id}: {flag} ({seconds:.1f}s)", flush=True)

    total = len(records)
    pct = lambda k: 100 * sum(1 for r in records if r.get(k)) / total  # noqa: E731
    seconds = [r["seconds"] for r in records]
    by_diff: dict[str, list[bool]] = defaultdict(list)
    for r in records:
        by_diff[r["difficulty"]].append(bool(r.get("match")))
    summary = {
        "label": label,
        "mode": args.mode,
        "split": args.split,
        "repair": args.repair,
        "retries": args.retries if args.repair else 0,
        "prompt_version": PROMPT_VERSION,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "n": total,
        "json_valid_pct": round(pct("json_ok"), 1),
        "guard_pass_pct": round(pct("guard_ok"), 1),
        "executes_pct": round(pct("exec_ok"), 1),
        "execution_accuracy_pct": round(pct("match"), 1),
        "by_difficulty": {d: f"{sum(v)}/{len(v)}" for d, v in sorted(by_diff.items())},
        "latency_s": {
            "p50": round(statistics.median(seconds), 2),
            "p95": round(percentile(seconds, 0.95), 2),
        },
        "avg_prompt_tokens": round(
            statistics.mean(r["prompt_tokens"] for r in records if r.get("prompt_tokens")), 0
        ),
        "errors": Counter(r["error"] for r in records if r.get("error")).most_common(8),
    }
    out_dir = REPO_ROOT / "eval" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{label}.json").write_text(
        json.dumps({"summary": summary, "items": records}, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
