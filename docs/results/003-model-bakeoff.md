# 003 - Model bake-off: Qwen2.5-Coder-1.5B vs Qwen3-4B-Instruct-2507

**Date:** 2026-11-07  **Raw results:** `eval/results/q3_4b_dev_norepair.json`, `q3_4b_dev_repair.json`, `q3_4b_dev_repair1.json`, `q3_4b_test_norepair.json`

## Hypothesis
A model ~3x larger understands the schema and business rules far better, at the cost of latency.

## Change
Same prompt (v1), same dictionary, same scorer; only the GGUF file changed. Challenger downloaded with
`scripts/setup_challenger.sh` (unsloth community GGUF re-pack of Qwen's Apache-2.0 weights, pinned commit,
SHA-256 checked, 2.5 GB, `models/qwen3-4b-instruct-2507/`). VRAM in use with the server up: 3.77 of 4.1 GB.

## Results (dev split, n=33, unless stated)
| Setup | Executes | Exec. accuracy | p50 s | p95 s |
|-------|----------|----------------|-------|-------|
| 1.5B, no repair | 75.8% | 51.5% (17) | 3.2 | 4.2 |
| 1.5B, repair x2 | 90.9% | 54.5% (18) | 3.4 | 12.4 |
| **4B, no repair** | 87.9% | **84.8% (28)** | 6.6 | 8.9 |
| 4B, repair x2 | 93.9% | 84.8% (28) | 6.6 | 14.0 |
| 4B, repair x1 | 93.9% | 84.8% (28) | 6.6 | 14.0 |
| **4B, no repair, TEST split (n=17), run once** | 88.2% | **76.5% (13)** | 6.7 | 9.1 |

Paired on dev, 4B fixed 12 questions the 1.5B got wrong and broke 1. The 1.5B's "business rule" mistakes
(open tickets, MRR statuses, definitions) mostly disappeared.

## What failed (4B, test)
commerce_06 and sales_hr_01 return wrong rows; subscriptions_06 sums a boolean; usage_04 puts a timestamp string
into an interval. The repair loop could rescue the last two (they are errors) but costs latency.

## Decision
Primary model = Qwen3-4B-Instruct-2507 Q4_K_M, repair OFF by default (accuracy unchanged, p95 inside 10 s).
Repair stays available (`--repair`) as a crash safety net. Even one retry costs ~7 s because the 3.5k-token prompt
is read again.

## Not proven
n=17 on test means roughly +/-20 points of uncertainty; 76.5% and the 70% target are statistically
indistinguishable. The dictionary and prompt were written after the golden questions existed, so some
indirect leakage is possible. p95 9.1 s is barely under the 10 s budget and the VRAM headroom is ~300 MB.
Next: grow the golden set (esp. test), try prompt-prefix caching to make retries cheap, then consider fine-tuning.
