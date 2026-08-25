# Legal Review Release Dossier - 2026-08-25

## Purpose

This dossier is the technical evidence package for an independent legal reviewer.
It does not decide legal correctness or authorize release. The reviewer must
score the candidate answers independently and record conflicts before a release
decision is made.

## Candidate Under Review

The review candidate is the completed hybrid control run. It is selected only
because it produced ten grounded answers; it is not a claim that the run meets
the legal-quality target.

| Item | Value |
|---|---|
| Candidate artifact | `docs/evals/stress-2026-08-25-hybrid-provider-healthy.xlsx` |
| SHA-256 | `D28E3156CEC459CBBB06882D0DA31B55B043C4BA8E6ADCA13627F3F090A09C62` |
| Cases | Set A, 10 |
| Answers / grounded outcomes | `10 / 10` |
| Citation revalidation | completed by grounded-chat service before answer release |
| Citation budget | 3 per case |
| Mean source coverage | `58.33%` |
| Cases with final expected-document hit | 5 |
| Route p50 / p95 | `13,419.00 / 26,033.26 ms` |

## Baseline and Release Rule

| Item | Value |
|---|---|
| Baseline artifact | `docs/Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx` |
| Baseline SHA-256 | `88B3AE50F0E135045C170772D7BDD5759B08C132FCB4979A31C21B7A5713FD30` |
| Baseline result | `5.49/10`, 4/10 PASS at `>=7.0` |
| Required average | `>=8.50/10` |
| Required Set A PASS count | `>=9/10` |
| Current legal-quality score | `NOT_MEASURED` |

The frozen score components are: substantive/legal correctness `4.0`,
authority/source/applicability `2.5`, completeness `2.5`, and presentation /
traceability / inference discipline `1.0`.

## Technical Verification

| Check | Evidence |
|---|---|
| Unit suite | `856 passed`, one non-failing OpenPyXL warning |
| Scoped lint | pass |
| Database migration | `0012_reviewed_legal_effects` |
| Corpus | 670 documents, 21,349 chunks, 42,690 embeddings |
| API health | local and public tunnel `/ready` returned 200 |
| Provider | successful full Set A candidate run; generation latency remains material |
| Benchmark leakage scan | no case-ID marker in production runtime scope |

## Retrieval and Selection Risks

1. Candidate coverage is incomplete: two expected identities are absent from
   the catalog and one is quarantined. These are source/corpus gaps, not a
   reviewer-authorized basis to infer missing law.
2. The candidate uses a fixed three-evidence budget. Multi-part questions can
   lose direct authority coverage at final selection.
3. Citation records are technically immutable and revalidated, but technical
   traceability does not prove that the selected document governs the claim.
4. The C07 quality ablation was executed after a generalized multi-unit merge
   repair. It is not a release candidate: 8/10 answers, two provider failures,
   43.33% source coverage and p95 `65,205.10 ms`.
5. Set B/C M2 retrieval controls had zero Set C invariant failures, but the
   mechanical gate was `HOLD_PENDING_ORACLE`: S1 did not improve expected hits
   and worsened non-expected cited rate.

## Reviewer Procedure

1. Verify the artifact SHA-256 values before reviewing.
2. Review each Set A answer blind to implementation/ablation labels.
3. For each material claim, verify that its supplied citation directly supports
   the claim; distinguish source fact, supported interpretation and limitation.
4. Record a score for each rubric component and identify unsupported,
   over-broad, incomplete, or applicability-uncertain conclusions.
5. Confirm citations/metadata are not merely technically valid but legally
   appropriate for the question.
6. Record reviewer conflicts and use independent adjudication where required.
7. Do not use Set B/C retrieval-only metrics as a substitute for scoring legal
   answers.

## Release Decision Template

| Condition | Reviewer record |
|---|---|
| Set A average >= 8.50 | pending |
| Set A PASS >= 9/10 | pending |
| Material claims supported/qualified | pending |
| Citation authority/applicability acceptable | pending |
| Set B/C safety and invariants reviewed | pending |
| Corpus gaps accepted or release-blocking | pending |
| Final decision: PASS / PASS_WITH_GAPS / NO_GO / BLOCKED | pending |

## Supporting Artifacts

- `docs/evals/stress-2026-08-25-hybrid-provider-healthy.xlsx`
- `docs/evals/stress-2026-08-25-quality-c07-fixed.xlsx`
- `docs/evals/set-bc-2026-08-25-m2.xlsx`
- `docs/evals/set-bc-2026-08-25-m2.json`
- `docs/evals/stress-2026-08-25-provider-and-retrieval-analysis.md`
- `docs/plans/quality-stress-test-2026-08-25.md`
