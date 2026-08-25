# Provisional Legal-Quality Score - Current P1-P10 Output

**Evaluation time:** 2026-08-25T16:53:59.9756879+07:00
**Evaluator:** Coding Agent, provisional application of the existing rubric
**Input:** `legal-quality-review-input.json` (`SHA-256: 6717452D862BEC3FDE3D7538D31ED2EAC86724785FFE66F07648FEA1B81A2533`)
**Scope:** Current 10-case P1-P10 deterministic-fallback output

This is a measured application of the earlier `4.0 + 2.5 + 2.5 + 1.0` rubric. It is not an independent full-text legal review and cannot establish the release target.

## Measurement rule

All current P10 outputs are `Evidence-bound diagnostic draft` texts. They report coverage states and `chunk` locators, but contain no substantive legal conclusion, rule, condition, procedure, exception, authority name, authority identifier, provision, or link. Therefore:

- correctness is capped at `0.4/4.0` for a safe non-fabricated limitation statement;
- governing-role evidence that is absent from the visible answer and has no applicability/current-effect treatment receives `0.6/2.5` at most;
- reporting `SUPPORTED` coverage without answering the legal issue receives `0.6/2.5` at most for completeness;
- chunk-only mapping receives `0.4/1.0` at most for traceability.

The full pre-registered rules and per-case observations are in the paired JSON artifact.

| Case | Correctness /4.0 | Authority /2.5 | Completeness /2.5 | Traceability /1.0 | Total /10 | Result |
|---|---:|---:|---:|---:|---:|---|
| Q01 | 0.4 | 0.0 | 0.2 | 0.3 | **0.9** | FAIL |
| Q02 | 0.4 | 0.6 | 0.5 | 0.4 | **1.9** | FAIL |
| Q03 | 0.4 | 0.0 | 0.2 | 0.3 | **0.9** | FAIL |
| Q04 | 0.4 | 0.6 | 0.5 | 0.4 | **1.9** | FAIL |
| Q05 | 0.4 | 0.6 | 0.6 | 0.4 | **2.0** | FAIL |
| Q06 | 0.4 | 0.6 | 0.6 | 0.4 | **2.0** | FAIL |
| Q07 | 0.4 | 0.6 | 0.5 | 0.4 | **1.9** | FAIL |
| Q08 | 0.4 | 0.6 | 0.5 | 0.4 | **1.9** | FAIL |
| Q09 | 0.4 | 0.6 | 0.5 | 0.4 | **1.9** | FAIL |
| Q10 | 0.3 | 0.2 | 0.2 | 0.4 | **1.1** | FAIL |

## Result

- **Average legal-quality score:** **1.64 / 10**
- **PASS:** **0 / 10**
- **Target average >= 8.50:** **NOT MET**
- **Target PASS >= 9 / 10:** **NOT MET**
- **Decision:** **NO_GO_FOR_LEGAL_QUALITY**

The prior independent score (`5.85/10`, `2/10 PASS`) belongs to `stress-2026-08-25-hybrid-provider-healthy.xlsx`, not this candidate. It remains historical context, not a comparable result or current baseline replacement.

## Boundary

The P1-P10 engineering-flow score remains separate. Successful terminal traversal, `SUPPORTED` coverage, governing evidence roles, citation integrity, retrieval behavior, or latency do not establish legal quality. Only P12 plus independent full-text legal review may establish the `>= 8.50/10` and `>= 9/10 PASS` release target.
