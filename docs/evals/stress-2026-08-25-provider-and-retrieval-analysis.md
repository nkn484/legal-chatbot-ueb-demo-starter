# Provider and Retrieval Analysis - 2026-08-25

## Measured Execution State

After recreating the API with the updated `.env`, local `/live`, local `/ready`
and public ngrok `/ready` returned `200`. The provider health operation
(`GET /models`) returned `healthy` for the configured model.

One short bounded generation probe timed out, but the completed Set A run then
produced ten valid non-streaming answers through the same adapter. The measured
run had `10/10 ANSWER_GROUNDED`, ten successful provider calls, no provider
output-parser failures, and three persisted citations per case. The earlier
probe timeout is retained as latency/availability risk, not as the final run
outcome.

## Release Target

No independent full-text legal score exists. The requested `>= 8.50/10` and
`>= 9/10 PASS` target is `NOT_MEASURED` and cannot be declared met. Structural
grounding, response production, and citation count do not replace the frozen
legal-review rubric.

## Retrieval and Selection Evidence

The immediately preceding completed hybrid Set A run used the same PostgreSQL
corpus and retrieval configuration. It produced three persisted citations per
case, but all final chats failed at the previous provider boundary. Its
retrieval-only evidence remains useful because provider configuration does not
alter the indexed corpus or ranking input.

| Observation | Measured interpretation |
|---|---|
| Source coverage | `33.33%` to `100%`, mean `58.33%` across Set A |
| Expected-document presence | Only five cases had a final expected-document hit |
| Corpus blockers | Two required identities were `NOT_IN_CATALOG`; one was `QUARANTINED` |
| Final evidence budget | Fixed at three citations per case |
| Analyzer / dynamic evidence / repair | Disabled in the legacy stress-runner profile |

## Root-Cause Classification

1. **Generation latency/availability risk:** one short bounded probe timed out,
   while the full run completed successfully with p95 route latency above
   twenty-six seconds. This is a performance risk, not a legal-answer score.
2. **Candidate-generation gaps:** documents absent from the catalog or
   quarantined cannot be recovered through query/ranking changes. They require
   separately approved source/corpus handling with provenance preserved.
3. **Query-construction limitations:** the legacy runner uses a raw hybrid
   query path. It does not use the deterministic bounded sub-intent/concept
   query construction required by the quality strategy.
4. **Final-evidence cutoff:** a hard three-document selection cannot generally
   preserve distinct authorities for multi-part legal questions. This is an
   evidence-budget/coverage issue, not a reason to hard-code benchmark cases.
5. **Selection directness:** hybrid similarity alone does not establish that a
   document is the direct governing authority. Role/coverage assessment must
   precede synthesis and preserve applicability limitations.

## Required Next Measurements

1. Freeze the successful provider/model configuration and latency protocol in a
   run manifest before another scored run.
2. Run sealed
   Set B and Set C.
3. Run the quality strategy ablation with generalized analyzer, coverage,
   dynamic evidence and one-shot repair enabled only through approved profiles.
4. Submit the resulting answers for blinded independent review using the frozen
   legal rubric. Only that review can establish the release target.
