# Results and improvements log

One place to see how the copilot's quality changes over time. Every experiment gets one entry file, so
we can always answer: what did we change, what did the numbers do, and what did we learn?

## How to use
1. Before a change: note the current numbers (from `eval/results/*.json`).
2. Make the change. Re-run `python scripts/run_baseline.py --mode all --label <name>`.
3. Copy `_TEMPLATE.md` to `NNN-short-name.md`, fill it in, add a row below. Commit raw JSON + entry together.

Rules: n=50 means 2 points = 1 question, so differences under ~6 points are noise. Always say which
prompt version, model file and mode were used. Never edit an old entry; add a new one.

## Scoreboard (execution accuracy on the 50 golden queries)

| # | Date | Change | Model | Prompt | Mode | Exec. acc. | Executes | p95 s | Entry |
|---|------|--------|-------|--------|------|-----------|----------|-------|-------|
| 001 | 2026-11-06 | First baseline, no retrieval, no repair | Qwen2.5-Coder-1.5B Q4_K_M | v1 | all tables | 52% | 76% | 4.5 | [001](001-first-baseline.md) |
| 001 | 2026-11-06 | same, perfect (oracle) table choice | same | v1 | oracle | 54% | 86% | 4.2 | [001](001-first-baseline.md) |

Targets (v1, agreed 2026-11-05, still a guess): >= 70% on held-out templates, p95 < 10 s, 100% of
red-team attacks blocked.

## Open questions we keep re-checking
- Is the score real, or is the model memorising golden-set wording? (Split by template once we train.)
- Do seed-data artifacts (see entry 001) make some golden questions too easy or ambiguous?
