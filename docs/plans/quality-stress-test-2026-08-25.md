# Quality Stress Test Plan - 2026-08-25

## Purpose and baseline

Re-run the ten-question legal-answer stress set against the current PostgreSQL
corpus and SHINE provider path. The 2026-08-22 full-text review workbook is
baseline evidence only: average `5.49/10`, `4/10 PASS`, where `PASS >= 7.0`.

The requested release target is stricter and remains the only release criterion:

- Set A average legal-quality score `>= 8.50/10`;
- at least `9/10` Set A answers `PASS` under the frozen rubric;
- no benchmark leakage, no Set C safety/invariant failure, and clean
  citation/provenance checks.

## Test Data and Privacy

- **Set A:** exactly the ten questions in
  `docs/Stress_test_Legal_Chatbot_UEB_10_cau.xlsx`.
- **Baseline:** `docs/Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx`.
- **Set B:** at least 30 pre-registered Vietnamese paraphrases, three or more
  per Set A case, withheld from production code.
- **Set C:** at least 20 pre-registered negative/control questions, including
  outside-corpus, ambiguous, insufficient-fact and near-match cases.

Questions, provider prompts, raw answers, user/channel identifiers and provider
credentials are not emitted in logs or JSON metrics. Expected identities are
post-run evaluation oracle data only and are never inputs to retrieval.

## Execution Sequence

1. Record run time, Git commit, corpus counts/hash, provider/model identifier,
   retrieval profile, retry policy and environment flags in a run manifest.
2. Confirm PostgreSQL migration/version, corpus readiness, `/live` and `/ready`.
3. Run Set A sequentially through `scripts/run_legal_chatbot_stress.py` with
   real SHINE enabled, preserving a timestamped XLSX report outside the baseline
   workbook. Mechanical calls are retained only as structural controls.
4. Run the same pre-registered Set A/B/C protocol for each approved ablation
   profile. C01-C04 retain three evidence items; C05+ may retain three to six;
   C06/C08 remain unavailable unless the reranker gate is approved.
5. Perform blinded independent legal review using the frozen rubric:
   substantive correctness `4.0`, authority/source/applicability `2.5`,
   completeness `2.5`, presentation/inference discipline `1.0`.
6. Compare aggregates, citation/provenance invariants and safety results against
   baseline. Keep at most three generalized remediations; do not tune on case
   IDs, expected document identities, titles or question literals.

## Current Run Boundary

The first re-run records transport, retrieval coverage and real provider answer
production for Set A. It is **not** a legal-quality release result until the
frozen, independent full-text review is completed. Missing Set B/C data or a
reviewer score must be reported as `NOT_MEASURED`, never estimated.

## Deliverables

- timestamped Set A stress-run XLSX;
- sanitized machine-readable run summary and comparison report;
- reviewer workbook/output produced only through the controlled review process;
- final `PASS`, `PASS_WITH_GAPS`, `NO_GO_QUALITY_TARGET_NOT_MET`, or
  `BLOCKED_EXTERNAL` decision backed by measured evidence.
