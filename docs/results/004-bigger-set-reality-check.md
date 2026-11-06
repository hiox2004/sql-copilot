# 004 - Reality check on the 150-item golden set (DB reseeded, prompt v2)

**Date:** 2026-11-07  **Raw results:** `eval/results/v2_q3_4b_dev_norepair.json` (and `v2_q3_4b_dev_repair1.json`, see below)

## Hypothesis
The 84.8% from entry 003 (n=33) overstated real quality; a larger, reviewed set will show a lower, more honest number.

## Change
- Seed fix: `random()` was evaluated once per query in three places (prospect leads, hire dates, email events); DB rebuilt, checks 37-39 added.
- Golden set 50 -> 150 items (100 new, written by Haiku agents, reviewed by an Opus agent; 16 weak items rewritten). Dev = 96 items, test = 54.
- Prompt v2: `tables_used` removed from the model output (tables are read from the SQL instead).
- Everything else identical to entry 003 (Qwen3-4B Q4_K_M, all tables in the prompt, no repair).

## Results (dev, n=96)
| Metric | Value |
|--------|-------|
| Execution accuracy | **63.5%** (61/96) |
| Executes without error | 85.4% |
| Valid JSON | 100% |
| By difficulty | easy 27/29, medium 26/44, hard 8/23 |
| p50 / p95 latency | 6.9 s / 9.3 s |

Outcome counts: 61 match, 21 wrong rows, 13 do not execute, 1 refused by the Guard.

## What failed
- 13 crashes: wrong interval syntax (2), invented/misplaced columns (`org_id`, `l.lead_id`, `s.rep_id`), a missing FROM entry. The repair loop targets these.
- 21 wrong-row answers, in rough groups: (a) extra or different columns than asked (support_03 adds `status`, commerce_17 adds `org_id`); (b) month shown as a number where the golden answer is a `YYYY-MM` string (sales_hr_19, subscriptions_24: arguably over-specified questions, to reword); (c) wrong table or join path (first agent reply measured with resolved_at, API usage joined through `addresses`); (d) missing window or status filter (win rate over all deals); (e) reading "customers" from `login_events` instead of `support_tickets`.

## Learned / next
The earlier 84.8% was flattered by a small, easy sample (and by questions written alongside the dictionary). On the harder, reviewed set the 4B model is at 63.5%, below the 70% target, and hard questions are the weak spot (35%). The model understands the schema but fails at multi-step reasoning and exact output shape, which is what fine-tuning on verified question/SQL pairs for this schema, or retrieved worked examples, should address. That makes the training-data generator the next build step. Not proven: that the gap is not partly the golden set's own strictness (extra columns count as wrong).

## Addendum: repair x1 on the same dev set
| Setup (dev, n=96) | Executes | Exec. accuracy | p50 s | p95 s |
|-------------------|----------|----------------|-------|-------|
| No repair | 85.4% | 63.5% (61) | 6.9 | 9.3 |
| Repair, 1 retry | 94.8% | 67.7% (65) | 7.3 | 17.2 |

Paired: repair fixed 4 questions (sales_hr_05, subscriptions_28, support_19, usage_27) and broke none. That is the right direction, but 4 vs 0 is not statistically significant (sign test p = 0.125). The price is p95 17.2 s, far over the 10 s budget, because each retry is a full second generation. So repair stays off by default; it could be offered as a slower "retry" option in the UI.
Decision: the test split (54 items) has not been spent on this set yet; it will be run once, after the next improvement.
