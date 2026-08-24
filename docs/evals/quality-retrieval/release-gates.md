# Frozen phase gates

All gates are evaluation decisions. Passing a gate never auto-enables production; `Reviewed Legal Effects` stays **OFF**.

| Gate | Required evidence | Frozen decision boundary |
|---|---|---|
| B — collapse | Collapse trace, recall/diversity, Set C | Zero duplicate document versions in final evidence; citation/provenance invariant passes; zero Set C invariant failures. |
| C — hybrid | Matrix 8/12/16/20, lane contribution, costs | Broad expected recall ≥27/29; lexical need not remain zero, but each accepted lane has measurable unique expected-identity contribution; apply Pareto pool policy; p95 end-to-end retrieval ≤2.45s and logical DB queries ≤12/case. |
| C — analyzer/protection | Deterministic analyzer trace; Q5/Q6/Q8; Sets B/C | Fail-closed, no leakage, no source quota; measure Q5/Q6/Q8 and Set B/C. Final expected recall ≥12/29 is only the continuation minimum after hybrid/analyzer, **not** final PASS. |
| D — dynamic/repair | Final evidence and repair trace | Final expected recall ≥20/29; false insufficiency 0/10; exactly one repair round maximum; citations 3–6 when eligible and no padding. |
| E — full | All eight configurations, expert review, Sets A/B/C | At least 8/10 expert scores ≥7, report the existing baseline 4/10 and average 5.49 plus before/after average; all user targets pass; no material B/C regression; Reviewed Legal Effects OFF; no production auto-enable. |

Set B regression threshold: mean Jaccard must be no worse than the semantic reference by more than 0.05, and evidence-decision consistency must be at least 90%. Set C allows zero invariant failures only.

The broad 27/29 target is a candidate/broad-retrieval target; the final 20/29 target is the requested final milestone PASS target. Do not substitute the 12/29 continuation threshold for either target.

A future blinded confirmation set is required before any production rollout. It is not required to complete this evaluation or to issue its GO/evaluation-only/NO-GO decision.
