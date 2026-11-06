# 002 - Verify and repair loop

**Date:** 2026-11-07  **Raw results:** `eval/results/v1_dev_norepair.json`, `v1_dev_repair.json` (first hint version), `v1_dev_repair2.json` (final)

## Hypothesis
About 24% of answers crash on invented columns; EXPLAIN plus real-schema hints should fix most of them.

## Change
`validation/verify.py` (Guard then EXPLAIN, error hints), `graph/repair.py` (max 2 retries), `--repair` flag.
Also in this round: column-order-insensitive scoring and the frozen dev/test split (33 dev / 17 test items;
14 test templates). Both runs below use the same new scorer.

## Setup
Qwen2.5-Coder-1.5B Q4_K_M, prompt v1, all tables in the prompt, dev split only (n=33).

## Results
| Metric (dev, n=33) | No repair | Repair v1 hints | Repair final hints |
|--------------------|-----------|-----------------|--------------------|
| Executes | 75.8% | 84.8% | 90.9% |
| Execution accuracy | 51.5% (17) | 54.5% (18) | 54.5% (18) |
| p50 latency | 3.2 s | 3.3 s | 3.4 s |
| p95 latency | 4.2 s | 12.5 s | 12.4 s |

## What failed
Items that still fail after 2 retries mostly return wrong rows (valid SQL, wrong meaning), not errors.
Only usage_10 flipped from wrong to right; nothing got worse.

## Learned / next
The loop works as a safety net (fewer crashes shown to users) but does not raise accuracy, and 2 retries break
the 10 s p95 budget. 1 question of change is within noise. Next: try 1 retry for latency; the real accuracy levers
are semantic (prompt/dictionary rules that get misapplied, e.g. "opened in the last 30 days" read as status open)
and fine-tuning. Not proven: that hints help more on the test split, or that results repeat run to run
(determinism at temperature 0 is unchecked).
