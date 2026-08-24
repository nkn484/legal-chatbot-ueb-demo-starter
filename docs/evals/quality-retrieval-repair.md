# Quality Retrieval Repair

## Recommendation: `NO_GO`

Phase B failed the frozen gate. Phase C–H were not run and no quality feature was enabled.

## Baseline and measured after-state

- Baseline broad recall: **24/29**
- Baseline final recall: **6/29**
- Phase B broad diagnostic top50: **24/29**
- Best release-pool recall: **20/29**
- Phase B final top3: **7/29**
- Title expected hits/rescue: **0**
- Lexical expected hits/rescue: **0**
- Semantic expected hits at diagnostic top50: **24**
- Reviewed Legal Effects: **OFF**

## Configuration table

| Configuration | Recall@20 | Final Recall | Source Coverage | False Insufficient | Wrong Docs | Latency |
|---|---:|---:|---:|---:|---:|---:|
| 1. Current default | 0/29 | 0/29 | 0% | 10/10 retrieval-availability proxy | 0 (no evidence selected) | p50 10.6 ms / p95 93.8 ms |
| 2. Document collapse only | 20/29 | 7/29 | 92.0% candidate-pool | NOT_MEASURED_PHASE_B | 23/30 | p50 406.5 ms / p95 8184.4 ms |
| 3. + Title/FTS/Semantic hybrid | 20/29 (pool20; pool matrix 15/17/19/20) | 7/29 | 96.0% candidate-pool | NOT_MEASURED_PHASE_B | 23/30 | p50 779.5 ms / p95 8425.5 ms |
| 4. + Query decomposition | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |
| 5. + Dynamic evidence | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |
| 6. + Reranker | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |
| 7. + Evidence repair | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |
| 8. Full candidate configuration | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |

## Pool matrix

| Pool | Expected recall | Final top3 | Non-expected identity rate | P95 retrieval ms | Data queries | Set C failures |
|---:|---:|---:|---:|---:|---:|---:|
| 8 | 15/29 | 7/29 | 81.2% | 8425.5 | 3 | 0 |
| 12 | 17/29 | 7/29 | 85.7% | 8425.5 | 3 | 0 |
| 16 | 19/29 | 7/29 | 87.7% | 8425.5 | 3 | 0 |
| 20 | 20/29 | 7/29 | 89.3% | 8425.5 | 3 | 0 |

No pool met the frozen Pareto/gate policy, so selecting one would be benchmark cherry-picking.

## Required findings

1. **Why 24/29 broad became 6/29 final:** chunk duplication consumed early budgets; document collapse improved pool recall, but semantic-only ranking and fixed top3 still discarded most expected documents. Phase B reached 7/29 final.
2. **Document collapse improvement:** +5 expected identities at pool8, +4 at pool20, 0 at diagnostic top50.
3. **Title lane rescue:** 0.
4. **Lexical lane:** still 0 expected hits.
5. **Candidate pool:** no defensible pool selected.
6. **Query decomposition:** `NOT_RUN_GATE_B_BLOCKED`.
7. **Reranker promotion/demotion:** `NOT_RUN_GATE_B_BLOCKED`.
8. **Dynamic evidence:** `NOT_RUN_GATE_B_BLOCKED`.
9. **False insufficient evidence:** `NOT_MEASURED_GATE_B_BLOCKED`.
10. **Full-text quality:** baseline 4/10 PASS, average 5.49; after-state not reviewed because Gate B blocked later phases.
11. **Paraphrase/control:** Set B mean Jaccard 0.413 with 100% evidence consistency; Set C invariant failures 0.
12. **Hard-code check:** no benchmark-specific production hard-code detected; expected identities were used only after retrieval for evaluation scoring.

## Q5 / Q6 / Q8

- **Q5:** broad diagnostic 2/3; pool20 0/3; final 0/3 — hard candidate cutoff remains.
- **Q6:** broad diagnostic 4/4; pool20 4/4; final 1/4 — final selection loses 3 expected identities.
- **Q8:** broad diagnostic 2/2; pool20 1/2; final 0/2 — cutoff/final selection remains unresolved.

## Safety and regression

- 136/136 evaluator citation scenarios resolved, cleaned, and preserved global DB counts.
- Set C invariant failures: 0.
- Main registry remained 0/0/0/0; Reviewed Legal Effects remained OFF.
- Production runtime and all quality feature flags remained unchanged/default OFF.

## Primary remaining bottleneck

Natural-question content FTS and title FTS produced no expected-identity contribution. Exact semantic remained the only effective lane, while its measured evaluation cost exceeded the frozen latency budget.

A new separately approved root-cause investigation is required before any further repair. No automatic tuning or production activation is authorized.
