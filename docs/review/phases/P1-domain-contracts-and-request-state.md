# Phase P1 - Domain Contracts and Request State

## Result

| Field | Value |
|---|---|
| Phase ID | `P1` |
| Phase name | Domain Contracts and Request State |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |
| Rollback status | `NOT_APPLIED`; all P1 source changes are additive and require no migration. |

## Delivered

- Added the pure `legal_chatbot.legal_evidence` package with immutable request-scoped contracts, the P1 truth/state enums, privacy-safe serialization, sequential stage transitions, evidence-backed relation promotion helpers, and future-facing pure ports.
- Added compatibility mappings from legacy quality-retrieval role and coverage labels. Legacy direct-authority labels map only to a proposal role; they do not assert verified applicability or legal truth.
- Added P1 unit tests for context construction, stage transitions, hint-versus-verified relation isolation, privacy, compatibility mapping, and import boundaries.
- No retrieval, provider, source, channel, database, migration, feature-flag, or runtime behavior was changed.

## Files changed

- `src/legal_chatbot/legal_evidence/__init__.py`
- `src/legal_chatbot/legal_evidence/compatibility.py`
- `src/legal_chatbot/legal_evidence/context.py`
- `src/legal_chatbot/legal_evidence/models.py`
- `src/legal_chatbot/legal_evidence/ports.py`
- `src/legal_chatbot/legal_evidence/transitions.py`
- `tests/unit/test_legal_case_context.py`
- `tests/unit/test_legal_case_privacy.py`
- `tests/unit/test_legal_truth_transitions.py`
- `tests/unit/test_demo_corpus.py`
- `docs/review/phases/P1-domain-contracts-and-request-state.md`
- `docs/review/phases/P1-domain-contracts-and-request-state.json`

The editable local dependency installation also regenerated tracked `src/legal_chatbot_ueb.egg-info` metadata. That generated metadata contains no P1 runtime logic.

## Tests and checks

| Command / scope | Result |
|---|---|
| P1 contract, privacy, and transition tests | `12 passed` |
| P1 plus related existing quality-contract/boundary tests | `50 passed` |
| Full suite with `--import-mode=importlib` | `875 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `pip check` | pass |
| `git diff --check` | pass |

## Gate evaluation

P1 contract validation, privacy serialization, forbidden proposal-to-verified promotion, import boundary checks, and default-off behavior pass. The new package has no adapter/runtime imports and is not wired into production composition.

The approved current-workbook expectation is `VBQPPL=452`, `VNU=307`, and `UEB=345`, with total rows `1,104`. The current catalog also has `1,104` unique external IDs and `1,104` valid SHA-256 values. Historical reports retain their prior snapshot measurements and are not overwritten.

The full suite now passes. The only warning is OpenPyXL reporting that a workbook Data Validation extension is not supported during read; the catalog contract still verifies all 1,104 rows, unique external IDs, and SHA-256 values.

Gate P1 is `PASS`: contracts and type validation pass; privacy serialization passes; proposal-only relation and applicability states cannot silently promote through P1 transitions; new behavior is not wired into runtime; and the full unit/integration collection is green under the repository-safe `--import-mode=importlib` collection mode.

## Known limitations

- `LegalCaseContext` is not yet wired to retrieval or chat. That is intentional P1 scope.
- Relation and applicability verification constructors establish P1 type boundaries only; they do not inspect document evidence until later phases.
- Historical 2026-08-21 corpus-import records retain the earlier workbook distribution as historical evidence.

## Engineering-versus-legal quality

This P1 result validates neither answer correctness nor legal release quality. No P1 test, citation integrity check, or contract result establishes the P12 legal target.
