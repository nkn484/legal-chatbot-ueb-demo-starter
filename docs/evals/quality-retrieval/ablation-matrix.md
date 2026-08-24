# Frozen ablation matrix

The machine contract is authoritative for IDs, versions, capabilities, pools, evidence bounds, reranker, and repair settings: `quality-retrieval-plan.contract.json`. All eight rows are release-evaluation rows; the separate references below are nonrelease controls.

| Order | Stable ID | Profile | Frozen configuration | Pool | Evidence | Reranker / repair |
|---:|---|---|---|---|---|---|
| 1 | QRRA2-C01 | `quality_retrieval_current_default_v1` | Current default | 3 | 3–3 | OFF / OFF |
| 2 | QRRA2-C02 | `quality_retrieval_document_collapse_v1` | Document collapse only | 8 | 3–3 | OFF / OFF |
| 3 | QRRA2-C03 | `quality_retrieval_hybrid_v1` | + Title/FTS/Semantic hybrid | matrix | 3–3 | OFF / OFF |
| 4 | QRRA2-C04 | `quality_retrieval_analyzer_protected_v1` | + Query decomposition/protected opportunity | selected matrix pool | 3–3 | OFF / OFF |
| 5 | QRRA2-C05 | `quality_retrieval_dynamic_evidence_v1` | + Dynamic evidence | selected matrix pool | 3–6 | OFF / OFF |
| 6 | QRRA2-C06 | `quality_retrieval_reranker_v1` | + Reranker | selected matrix pool | 3–6 | ON, input ≤20 / OFF |
| 7 | QRRA2-C07 | `quality_retrieval_evidence_repair_v1` | + Evidence repair | selected matrix pool | 3–6 | OFF / exactly one round |
| 8 | QRRA2-C08 | `quality_retrieval_full_candidate_v1` | Full candidate configuration | selected matrix pool | 3–6 | ON, input ≤20 / exactly one round |

### Internal subrows for configuration 3

`QRRA2-C03-P08`, `QRRA2-C03-P12`, `QRRA2-C03-P16`, and `QRRA2-C03-P20` are required result rows, respectively using pools 8, 12, 16, and 20. They are evaluated before the frozen Pareto policy is applied.

### Nonrelease controls

* `QRRA2-NR01`: natural exact semantic top50, 24/29 candidate availability.
* `QRRA2-NR02`: Phase-4 semantic-rerank final reference, 8/29.
* `QRRA2-NR03`: M2 metadata repair negative comparator, 8/29 → 8/29 with worse noise/latency; it cannot win.

These controls provide context and do not compete for release selection. The current default lexical `NO_RESULTS` control is also not a quality baseline.

### A1 reconciliation boundary

A1's immutable ablation registry now owns and uses the eight exact A2 profile names. The current-default row remains a non-materializable release control; all rows are no-padding, with 3–3 evidence before dynamic evidence and 3–6 after it. A2 validates names through contract tests rather than importing production code. No arbitrary environment subflag combination is valid, and no profile is automatically enabled.
