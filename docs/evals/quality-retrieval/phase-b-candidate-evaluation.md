# Quality Retrieval Phase B

Gate B: **NO_GO_PHASE_B**. Selected pool: `None`.

| Pool | Expected candidate hits | Nonexpected identity rate | P95 retrieval-eval ms | Data queries | Set C failures |
|---:|---:|---:|---:|---:|---:|
| 8 | 15 | 0.812 | 8425.5 | 3 | 0 |
| 12 | 17 | 0.857 | 8425.5 | 3 | 0 |
| 16 | 19 | 0.877 | 8425.5 | 3 | 0 |
| 20 | 20 | 0.893 | 8425.5 | 3 | 0 |

Collapse lift @8: `5`. Title rescue: `0`. Lexical rescue: `0`. Recall: `{'fused_diagnostic_top50_expected_hits': 24, 'fused_candidate_expected_hits': {'8': 15, '12': 17, '16': 19, '20': 20}, 'final_top3_expected_hits': {'8': 7, '12': 7, '16': 7, '20': 7}}`. Semantic reference latency is embedding plus measured semantic-lane data elapsed; isolated semantic collapse timing is not separately measured. Analyzer/dynamic/rerank/insufficiency/full-text: **NOT_MEASURED_PHASE_B**. This is evaluation-only, not production behavior or a legal correctness claim.
