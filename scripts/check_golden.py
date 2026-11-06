"""Verify golden-query files: format, Guard, execution, determinism.

Usage:  python scripts/check_golden.py data/eval/golden/billing.yaml [more files...]
For each item prints OK/FAIL, the row count and a preview of the first row, so the author can see
whether the answer is plausible. Exit code is non-zero if any item fails.
"""

import sys
from pathlib import Path

import psycopg

from t2sql.core.config import REPO_ROOT, Settings
from t2sql.core.profile import load_profile
from t2sql.core.result_compare import results_match
from t2sql.dialects import get_dialect
from t2sql.retrieval.dictionary import load_dictionary
from t2sql.validation.executor import run_guarded
from t2sql.validation.golden import load_golden_file
from t2sql.validation.guard import GuardViolation, guard_sql

MAX_ANSWER_ROWS = 100


def check_item(item, conn, guard_kwargs) -> tuple[bool, str]:
    try:
        guarded = guard_sql(item.sql, **guard_kwargs)
    except GuardViolation as exc:
        return False, f"guard refused: {exc}"
    try:
        first = run_guarded(conn, guarded.sql)
        second = run_guarded(conn, guarded.sql)
    except psycopg.Error as exc:
        return False, f"database error: {str(exc).strip()[:200]}"
    if not results_match(first.rows, second.rows, order_matters=item.order_matters):
        return False, "not deterministic: two runs returned different rows (add ORDER BY ties?)"
    if item.order_matters and first.rows != second.rows:
        return False, "order is not stable between runs: add a tie-breaker to ORDER BY"
    if len(first.rows) > MAX_ANSWER_ROWS:
        return False, f"answer has {len(first.rows)} rows; keep it <= {MAX_ANSWER_ROWS}"
    if not first.rows and not item.expect_empty:
        return False, "returned 0 rows (expect_empty: true only if truly correct)"
    if first.rows and all(v is None for row in first.rows for v in row):
        return False, "returned only NULLs"
    if first.rows and item.expect_empty:
        return False, "expect_empty is true but rows came back"
    preview = str(first.rows[0])[:90] if first.rows else "(empty)"
    return True, f"{len(first.rows)} row(s); first: {preview}"


def main(paths: list[str]) -> int:
    profile = load_profile(REPO_ROOT / "data" / "profiles" / "saas.yaml")
    dictionary = load_dictionary(REPO_ROOT / profile.dictionary)
    guard_kwargs = {
        "dialect": get_dialect(profile.dialect),
        "allowed_tables": set(dictionary.tables),
        "blocked_columns": dictionary.blocked_columns(),
    }
    failures = 0
    with psycopg.connect(Settings.from_env().ro_dsn) as conn:
        for path in paths:
            golden = load_golden_file(Path(path))
            print(f"== {path}: domain={golden.domain}, {len(golden.items)} items")
            for item in golden.items:
                ok, message = check_item(item, conn, guard_kwargs)
                failures += not ok
                print(f"  {'OK  ' if ok else 'FAIL'} {item.id}: {message}")
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
