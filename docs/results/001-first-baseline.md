# 001 - First baseline

**Date:** 2026-11-06  **Raw results:** `eval/results/baseline_all_v1.json`, `eval/results/baseline_oracle_v1.json`

## Hypothesis
A small untuned model with the schema in the prompt gets some questions right; this sets the floor.

## Change
None; this is the starting point (no retrieval, no repair loop, no fine-tuning).

## Setup
Qwen2.5-Coder-1.5B-Instruct, Q4_K_M GGUF, llama-server (CUDA 12.4 build) on the RTX 3050 4 GB,
prompt v1, JSON-schema-constrained output, n = 50 golden queries. "all" = every table in the prompt;
"oracle" = only the tables the golden query needs (what perfect retrieval would give).

## Results
| Metric | all tables | oracle tables |
|--------|-----------|---------------|
| Execution accuracy | 52% | 54% |
| Executes without error | 76% | 86% |
| Valid JSON | 100% | 98% |
| p50 latency | ~3.3 s | ~3.5 s |
| p95 latency | ~4.5 s | ~4.2 s |

## What failed
About 25% of answers reference columns or tables that do not exist ("invented columns").
Other failures: wrong business definition, wrong date window, wrong join.

## Learned / next
Perfect retrieval added only 2 points (1 question), so retrieval is not the bottleneck at this size.
The bigger levers are the verify-and-repair loop (targets invented columns) and fine-tuning.
Caveats: n=50 is noisy; seed-data artifacts (all 133 lost deals share one `closed_at`; ads/email
channels convert at 100%; commerce_06 failure rates are 0%) can make some golden questions
uninformative and should be fixed.
