# Quality Retrieval Repair A2 evaluation freeze

**Status:** evaluation-plan freeze only. This pack authorizes neither a runtime change nor a production enablement.

## Frozen inventory and baselines

The quality milestone denominator is **29 retrievable expected identity case-occurrences** verified by Prompt-01. The inventory rule is: count an expected identity once for each originating case; do not deduplicate the same identity across different cases; do not count duplicate document versions twice inside one case-occurrence. Older reports' **26** is the number of distinct expected document families, not the quality denominator. It must never be mixed with 29 in a ratio or comparison.

| Reference | Frozen result | Role |
|---|---:|---|
| Current default lexical | `NO_RESULTS` | Safe control; not a quality baseline |
| Natural exact semantic top50 | 24/29 candidate availability | Candidate reference |
| Production-equivalent final top3 | 6/29 final availability | Requested-milestone quality baseline |
| Phase-4 semantic-rerank | 8/29 final availability | Nonrelease final-evaluation reference |
| M2 metadata repair | 8/29 → 8/29; noise and p50 latency worse | Negative comparator; cannot win |

M2's non-expected cited rate worsened from 72.4% to 73.3%, and p50 latency from 1.16s to 2.01s. It is excluded from tuning and selection.

## Sets and scoring boundaries

* **Set A:** Prompt-01's 10 expert cases and 29 expected identity case-occurrences. Retrieval measures and expert full-text review are here. Legal correctness is evaluated only through the Set A expert full-text review.
* **Set B:** existing 30 paraphrases. It measures stability only: mean Jaccard and evidence-decision consistency. It makes no legal-truth assertion.
* **Set C:** existing 24 safety controls. It measures safety invariants only, not relevance or legal truth.
* The M2 JSON's canonical SHA-256, B=30, C=24, and the seven-category C distribution are pinned in `quality-retrieval-plan.contract.json`. They are loaded and checked by the offline validator.

All runs use the same frozen Set A expected-identity inventory. Oracle identifiers are used only after scoring to classify a run; they are never passed to retrieval, analyzer, reranker, repair, or configuration selection.

## Pre-result pool policy

Run all hybrid pool subrows 8, 12, 16, and 20. Pool 8 compares to the frozen natural exact semantic top50 reference; pool 12 compares to 8, 16 to 12, and 20 to 16. A later pool still compares to its immediate prior measurement if that prior failed safety, while each current pool must independently meet the absolute safety limits. A pool is Pareto eligible only when it satisfies all of:

1. expected-identity candidate availability increases by at least one case-occurrence **or** availability has no loss and latency is lower;
2. non-expected candidate rate is no worse by more than 2 percentage points;
3. reranker input is at most 20 and its measured latency stays within the frozen end-to-end budget.

If several pools qualify, select the smallest. A larger pool cannot be selected merely because it is the benchmark maximum. The selected pool is then the inherited pool for later configurations; this is a policy decision after the matrix, not benchmark tuning.

## Measurement execution rules

Measure the same configuration/version and pool per case before aggregates. Record a null only where a DB engine does not expose a stated cost counter; do not synthesize it. End-to-end retrieval latency covers bounded retrieval work through final evidence selection, including reranking and the one permitted repair read, but excludes model answer generation and human review. Logical database query count is the count of SQL statements issued by the retrieval operation, capped at 12 per case.

Analyzer input is deterministic and fail-closed: NFC/token analysis, at most four units, and no generated document numbers. It has no legacy LLM planner/provider call and no model-based query rewrite. The required `RETRIEVAL_QUALITY_QUERY_PLANNER_ENABLED` name is a compatibility environment alias for the deterministic analyzer only. Observation source scope is derived strictly from authoritative unit scopes: any ambiguous unit wins, otherwise any explicit unit wins, otherwise it is none; this does not resolve, prioritize, or rank sources. A protected opportunity preserves at most one eligible collapsed candidate per detected unit or explicit source opportunity. It is not a source quota, output quota, authority ranking, or citation guarantee. Raw analyzer and repair text stays memory-only.

Metadata/title candidates require an exact supporting-child semantic score when used for audit; it is private audit data, not an independent fusion lane or legal-relevance proof. Diagnostic fused top50 is recall measurement only: it is not release eligible and cannot choose a candidate pool or final evidence.

`Reviewed Legal Effects` remains **OFF** throughout. This work makes no authority, effect, hierarchy, replacement, currentness, completeness, or legal applicability claim.
