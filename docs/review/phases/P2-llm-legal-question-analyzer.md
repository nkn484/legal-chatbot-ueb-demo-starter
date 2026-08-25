# Phase P2 - LLM Legal Question Analyzer

## Result

| Field | Value |
|---|---|
| Phase ID | `P2` |
| Phase name | LLM Legal Question Analyzer |
| Implementation status | `IMPLEMENTATION_COMPLETE` |
| Live LLM quality | `LIVE_LLM_QUALITY_NOT_ESTABLISHED` |
| Deterministic fallback | `DETERMINISTIC_FALLBACK_VERIFIED` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |
| Rollback status | `NOT_APPLIED`; P2 code is additive, default-off, and has no migration. |

## Delivered

- Added a default-off LLM question analyzer through `LLMProviderPort`; it has no provider-specific client or runtime wiring.
- Added a strict JSON prompt/parser contract with one through four material sub-intents, no document identifiers, no legal conclusions, and source-tier preferences explicitly modeled as proposals only.
- Added bounded question, organization, and conversation context fields to the P1 request model. All remain memory-only and excluded from public serialization.
- Added a deterministic fallback backed by the existing pure `retrieval.quality_repair.LegalQuestionAnalyzer` for disabled, unavailable, failed, timed-out, or invalid-provider-output cases.
- Added a 30-paraphrase contract fixture with fake-provider output and a benchmark-leakage/import-boundary scan.
- Added an evaluation-only canonical Set B loader, hash verification, taxonomy normalizer, exact-set measurement, and controlled provider runner. None are imported by production runtime.
- Remediated the controlled runner with per-case timeout, bounded transient retry/backoff, default concurrency three, atomic per-case checkpoints, and hash/version-guarded resume.
- Added provider-reported output-token telemetry and controlled timing samples before any output-budget reduction.
- No provider call is enabled in runtime; no retrieval, source, channel, database, migration, feature flag, or production profile behavior changed.

## Files changed

- `src/legal_chatbot/legal_evidence/__init__.py`
- `src/legal_chatbot/legal_evidence/context.py`
- `src/legal_chatbot/legal_evidence/models.py`
- `src/legal_chatbot/legal_evidence/ports.py`
- `src/legal_chatbot/legal_evidence/analyzer/__init__.py`
- `src/legal_chatbot/legal_evidence/analyzer/models.py`
- `src/legal_chatbot/legal_evidence/analyzer/parser.py`
- `src/legal_chatbot/legal_evidence/analyzer/prompt.py`
- `src/legal_chatbot/legal_evidence/analyzer/service.py`
- `src/legal_chatbot/diagnostics/evaluation/set_b_material_subintent.py`
- `scripts/evaluate_p2_set_b_analyzer.py`
- `src/legal_chatbot/providers/models.py`
- `src/legal_chatbot/providers/adapters/shineshop.py`
- `tests/unit/test_legal_case_privacy.py`
- `tests/unit/test_legal_llm_question_analyzer.py`
- `tests/unit/test_set_b_material_subintent_oracle.py`
- `tests/unit/test_p2_set_b_execution.py`
- `tests/unit/test_shineshop_adapter.py`
- `docs/evals/oracle/set-b-material-subintent-oracle-v1.0.0.json`
- `docs/evals/oracle/set-b-material-subintent-oracle-review-v1.0.0.md`
- `docs/evals/p2-set-b-material-subintent-2026-08-25.json`
- `docs/evals/p2-set-b-sample-one-2026-08-25.json`
- `docs/evals/p2-set-b-sample-three-2026-08-25.json`
- `docs/review/phases/P2-llm-legal-question-analyzer.md`
- `docs/review/phases/P2-llm-legal-question-analyzer.json`

## Tests and checks

| Command / scope | Result |
|---|---|
| P1/P2 context, transition, privacy, and analyzer tests | `19 passed` |
| Canonical Set B oracle loader, hash, taxonomy, and exact-match tests | `3 passed` |
| Execution timeout/retry/concurrency/checkpoint/resume tests | `4 passed` |
| Provider output-token telemetry and parser-rejection classification tests | `3 passed` |
| Contract fixture, 30 paraphrases | `30/30` matching material-sub-intent signatures, `100%` |
| Controlled live Set B run | `30 TIMEOUT`, `0 COMPLETE`, `0 semantic mismatch`; artifact terminal `BLOCKED_PROVIDER_EXECUTION` |
| P2 timing sample, one case then three sequential representative cases | no valid completed analyzer measurement; observed generation durations `17.48s`, `21.31s`, `29.04s` on invalid outputs; output usage `814-1049` |
| Final P2 timing sample | `TIMEOUT` at `55.09s` with request timeout `55s` and hard case timeout `60s` |
| Full suite with `--import-mode=importlib` | `891 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `pip check` | pass |
| `git diff --check` | pass |

## Gate evaluation

The engineering contract portions of P2 pass: strict output validation, maximum four material sub-intents, deterministic fallback, default-off behavior, prompt isolation, and static benchmark-leakage checks all pass.

The canonical Set B oracle is now available and valid. Its canonical SHA-256 matches the reviewer-provided value; it contains ten parent gold sets and the expected 30 Set B paraphrases resolve to those parents. The evaluator applies the frozen exact-set rule and treats missing, extra, or unmapped material sub-intents as a mismatch.

The first remediated controlled provider measurement completed its bounded execution with a versioned artifact. Its manifest freezes the canonical oracle hash, evaluation-set hash, provider/model, analyzer/prompt/normalizer versions, concurrency `3`, retry limit `2`, and exponential backoff base `0.5s`. Every case reached `TIMEOUT`; no case reached `COMPLETE`, and no execution failure was counted as a semantic mismatch. Consequently the semantic measurement is `null`, not `0%`.

The stage-specific request timeout started at `45s` with a `60s` hard case cap. A single measured `45.08s` request timeout justified increasing only the P2 request timeout to `55s`; the hard cap remains `60s`. A final one-case sample still timed out at `55.09s`. The three successful transport responses preceding that sample were invalid structured outputs and reported `814-1049` output tokens, so the 512-token budget is not reduced. No global chatbot timeout was changed.

The 30-paraphrase fake-provider fixture and failure-path tests verify deterministic fallback. They do not establish canonical Set B agreement, provider quality, legal quality, or the P12 release target. Per the implementation decision, P2 is closed as implementation-complete while live LLM quality remains not established; P3 may proceed independently.

## Known limitations

- A provider execution that yields `30/30 COMPLETE` analyzer measurements is required before live LLM analyzer quality can be established.
- The current provider behavior prevents a successful timing sample under the bounded `55s/60s` P2 configuration.
- The analyzer remains default-off and has not been composed into runtime, so no live provider behavior has been asserted.
- P2 outputs are proposals only; they cannot declare authority, current legal effect, relation truth, or case-specific applicability.

## Engineering-versus-legal quality

P2's passing engineering checks do not establish legal-answer correctness, authority, applicability, completeness, or the P12 legal-quality release target.
