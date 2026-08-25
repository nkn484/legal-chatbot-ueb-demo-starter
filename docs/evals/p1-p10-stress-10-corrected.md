# P1-P10 Corrected Ten-Case Stress Run

Runtime profile: `LEGAL_CHAT_PIPELINE_ENABLED=true`, P2 deterministic-first,
P4 deterministic classifier fallback, P11 OFF, real PostgreSQL P3/P6/P8 readers.

| Metric | Result |
| --- | --- |
| Terminal cases | 10 / 10 |
| Unhandled exceptions | 0 / 10 |
| Completion | 100% |
| Engineering flow score | 10.0 / 10 |
| Median terminal duration | 3.19 seconds |

Q01 and Q03 now complete as `ANSWER_WITH_LIMITATION`: P5 has no eligible
authority family, P6 returns an empty no-family outcome, P7 marks the issue
unsupported and P10 returns a limitation-bound answer. Q08 completes after
generic retrieval-concept normalization deduplicates input terms.

This is an engineering score only. It does not self-score legal correctness,
authority, completeness or release readiness.
