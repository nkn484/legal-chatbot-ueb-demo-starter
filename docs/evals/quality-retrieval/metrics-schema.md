# Metrics dictionary and record contract

Use `quality-retrieval-metrics.schema.json` for every per-configuration record and each per-case row. Raw request, answer, prompt, query, chunk, and URL fields are deliberately absent. A repair trace permits only class, opaque unit ID, and count/round information.

| Metric | Numerator | Denominator / rule |
|---|---|---|
| Expected recall@8/@20/@50 | Set A expected identity case-occurrences present at rank ≤ k | 29 expected identity case-occurrences |
| Final expected recall | Set A expected identity case-occurrences retained in final evidence | 29 |
| Direct-title hit | Expected identity case-occurrences directly observed by title lane | 29 |
| Lexical / semantic expected hit | Expected identity case-occurrences observed by the named lane before fusion | 29 each |
| Source coverage | Distinct expected source IDs represented by a retained expected identity | Distinct expected source IDs in the frozen Set A inventory |
| Sub-intent coverage | Expected annotated Set A unit-occurrences with a retained expected identity | Expected annotated Set A unit-occurrences; no double-counting from duplicate versions |
| Wrong-document rate | Non-expected final document selections | All final document selections; a no-final case contributes zero to both |
| False insufficient | Set A cases classified insufficient while eligible expected evidence was final | 10 Set A cases |
| Reranker promoted/demoted expected/wrong | Matching expected or non-expected identities whose rank improves/worsens across pre/post rerank | Matching identities present in both pre/post lists; null when reranker is OFF |
| Latency p50/p95 and per case | N/A | Milliseconds over per-case end-to-end retrieval timings; definition is in methodology |
| DB/query cost | N/A | Per-case and aggregate `query_count`, `lane_ms`, `transaction_ms`, `rows`, `buffer_hits`, `buffer_reads`; null only when not measured |
| Answer grounded | Answer-bearing cases where every emitted citation resolves to retained retrieved evidence | Answer-bearing cases evaluated; no legal-truth conclusion |
| Evidence count | Sum of retained final evidence items | Cases evaluated; retain 3–6 where eligible and never pad when fewer than three eligible items exist |
| Candidate-to-final loss | Expected candidate case-occurrences not retained final | Expected candidate case-occurrences before final selection |
| Invariant failures | Failed invariant checks | Count, not a rate; every required invariant must be zero |

Set B only reports mean Jaccard (mean per-parent set Jaccard over the 30 paraphrases) and evidence-decision consistency (paraphrases with the same evidence decision as their parent divided by 30). Set C only reports invariant failures. Neither Set B nor Set C establishes legal correctness.

The aggregate report must retain the component numerator and denominator instead of only a rounded percentage. Values unavailable from the engine are `null`, never zero. Result artifacts are future outputs and are not created by this freeze.
