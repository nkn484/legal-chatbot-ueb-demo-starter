# Phase P5 - Authority Family and Relation Investigation

## Result

| Field | Value |
|---|---|
| Phase ID | `P5` |
| Phase name | Authority Family and Relation Investigation |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |
| Rollback status | `NOT_APPLIED`; P5 is additive, default-off, and has no migration. |

## Delivered

- Added proposal-only relation hints with optional default-off LLM proposal and deterministic empty fallback.
- Added relation evidence markers that must exactly match the hinted relation type before `EVIDENCE_VERIFIED` relation construction.
- Built authority families only from immutable candidate identity plus verified relation links; date, title, issuer, and similarity do not create families or relations.
- Retained unmatched hints as hints and did not promote them to legal facts.
- Added conflict representation for multiple verified relation types on the same ordered endpoints.
- No Reviewed Legal Effects import, automatic registry mutation, DB write, current-effect conclusion, or runtime activation was introduced.

## Files changed

- `src/legal_chatbot/legal_evidence/relations/__init__.py`
- `src/legal_chatbot/legal_evidence/relations/models.py`
- `src/legal_chatbot/legal_evidence/relations/service.py`
- `tests/unit/test_legal_relation_investigation.py`
- `docs/review/phases/P5-authority-family-relation-investigation.md`
- `docs/review/phases/P5-authority-family-relation-investigation.json`

## Tests and checks

| Command / scope | Result |
|---|---|
| P5 relation/family/no-registry tests | `3 passed` |
| Full suite with `--import-mode=importlib` | `902 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `git diff --check` | pass |

## Gate evaluation

Relation hints remain separate from verified facts. A verified relation is constructed only with an `EvidenceReference` and a matching explicit marker. Family grouping is deterministic from verified endpoints. The P5 package has no Reviewed Legal Effects importer dependency and does not write registry state.

## Known limitations

- P5 is default-off and no live provider-quality assertion is made.
- A future relation-evidence reader must inspect explicit source text and emit only the sanitized marker plus resolvable locator.
- P5 does not establish current legal effect, applicability, citations, answer correctness, or the P12 legal-quality target.
