# Legal-Quality Provisional Rubric Review

## Decision

`NO_GO_FOR_LEGAL_QUALITY`

The 10 measured outputs are safe diagnostic records, not legal answers. Each P10 response reports coverage and selected `chunk` locators, but none gives a substantive answer to the underlying legal question. No response visibly identifies a controlling instrument, explains applicability/current effect, states a provision, or maps a legal proposition to a provision-level citation.

## Measured result

| Metric | Result |
|---|---:|
| Average score | `1.64 / 10` |
| Cases passing `>= 7.0` | `0 / 10` |
| Release average target `>= 8.50` | `NOT MET` |
| Release pass-count target `>= 9 / 10` | `NOT MET` |

The score is recorded in `docs/evals/legal-quality-provisional-rubric-score.json` with the SHA-256 of its source evaluator input, a fixed scoring rule, all component scores, and per-case findings.

## What the result does and does not establish

It establishes only that the current visible P10 output cannot meet the existing legal-answer rubric. It does not invalidate the P1-P10 engineering-flow measurement, and it is not an independent legal review or a P12 result.

The necessary next evaluation is independent full-text legal review after the composer produces substantive evidence-bound answers with visible authority and provision-level citations. No release target can be claimed before that evaluation.
