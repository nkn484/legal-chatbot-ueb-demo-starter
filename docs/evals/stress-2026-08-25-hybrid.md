# Set A Hybrid Stress Test - 2026-08-25

## Scope

This is a measured Set A re-run of the ten-question legal-answer stress set.
The runner used the current PostgreSQL corpus, hybrid semantic plus lexical
retrieval, the configured SHINE provider port, and a healthy local API probe.
The 2026-08-22 full-text workbook remains baseline evidence only.

## Runtime Evidence

| Item | Measured value |
|---|---:|
| Database migration | `0012_reviewed_legal_effects` |
| Documents / chunks / embeddings | `670 / 21,349 / 42,690` |
| API `/live` and `/ready` | `200 / 200` |
| Public ngrok `/live` | `200` |
| API probe network errors | `0` |
| Semantic mode | `hybrid` |
| Semantic embedding calls | `20`, all successful |
| Real SHINE cases attempted | `10` |
| Answer provider calls, success / failure | `10`, `0 / 10` |
| Real chat route p50 / p95 ms | `1130.28 / 2118.21` |

## Results

- Every Set A case created three persisted retrieval citations.
- Real provider outcomes: `10 REFUSAL`, all with `PROVIDER_FAILURE`.
- Provider health was `unhealthy` with normalized error code `unavailable`.
- Source coverage ranged from `33.33%` to `100%`; two expected documents were
  absent from the catalog and one was quarantined.
- The generated workbook is
  `docs/evals/stress-2026-08-25-hybrid.xlsx`. It contains the case-level
  answers/output fields, citations, coverage and diagnostics; this summary
  deliberately contains no raw question, answer, prompt or credential text.

## Baseline Comparison and Decision

The 2026-08-22 independent full-text baseline was `5.49/10` with `4/10 PASS`
at the frozen `PASS >= 7.0` threshold. This run has no valid full-text legal
score because SHINE produced no answers. It cannot be compared numerically with
the baseline and cannot satisfy the requested `>= 8.50/10` and `>= 9/10 PASS`
release target.

**Decision: `BLOCKED_EXTERNAL`.** Correct the provider availability/configuration,
then re-run the pre-registered Set A/B/C protocol and obtain blinded independent
legal review before any release decision.
