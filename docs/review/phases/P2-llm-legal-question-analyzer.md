# Phase P2 - LLM Legal Question Analyzer

## Result

| Field | Value |
|---|---|
| Phase ID | `P2` |
| Phase name | LLM Legal Question Analyzer |
| Implementation status | `COMPLETE` |
| Gate status | `BLOCKED` |
| Decision | `REWORK` |
| Next phase allowed | `NO` |
| Rollback status | `NOT_APPLIED`; P2 code is additive, default-off, and has no migration. |

## Delivered

- Added a default-off LLM question analyzer through `LLMProviderPort`; it has no provider-specific client or runtime wiring.
- Added a strict JSON prompt/parser contract with one through four material sub-intents, no document identifiers, no legal conclusions, and source-tier preferences explicitly modeled as proposals only.
- Added bounded question, organization, and conversation context fields to the P1 request model. All remain memory-only and excluded from public serialization.
- Added a deterministic fallback backed by the existing pure `retrieval.quality_repair.LegalQuestionAnalyzer` for disabled, unavailable, failed, timed-out, or invalid-provider-output cases.
- Added a 30-paraphrase contract fixture with fake-provider output and a benchmark-leakage/import-boundary scan.
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
- `tests/unit/test_legal_case_privacy.py`
- `tests/unit/test_legal_llm_question_analyzer.py`
- `docs/review/phases/P2-llm-legal-question-analyzer.md`
- `docs/review/phases/P2-llm-legal-question-analyzer.json`

## Tests and checks

| Command / scope | Result |
|---|---|
| P1/P2 context, transition, privacy, and analyzer tests | `19 passed` |
| Contract fixture, 30 paraphrases | `30/30` matching material-sub-intent signatures, `100%` |
| Full suite with `--import-mode=importlib` | `882 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `pip check` | pass |
| `git diff --check` | pass |

## Gate evaluation

The engineering contract portions of P2 pass: strict output validation, maximum four material sub-intents, deterministic fallback, default-off behavior, prompt isolation, and static benchmark-leakage checks all pass.

The canonical Set B gate cannot be measured. `docs/evals/m2_evaluation_set.json` contains 30 Set B paraphrases, but no independently annotated parent material-sub-intent sets. The later `set-bc-2026-08-25-m2.json` report contains evidence-stability observations, not material-sub-intent annotations. Therefore the required metric, “canonical Set B material sub-intent agreement >=90%,” cannot be computed without inventing an oracle.

The 30-paraphrase fake-provider fixture is intentionally only a schema/service stability test. It does not establish canonical Set B agreement, provider quality, legal quality, or the P12 release target. Consequently P2 cannot receive a `PASS`, and P3 cannot start.

## Known limitations

- A controlled, independently annotated Set B parent-sub-intent artifact is required before the P2 gate can be completed.
- The analyzer remains default-off and has not been composed into runtime, so no live provider behavior has been asserted.
- P2 outputs are proposals only; they cannot declare authority, current legal effect, relation truth, or case-specific applicability.

## Engineering-versus-legal quality

P2's passing engineering checks do not establish legal-answer correctness, authority, applicability, completeness, or the P12 legal-quality release target.
