# Phase P4 - LLM Authority Reviewer

## Result

| Field | Value |
|---|---|
| Phase ID | `P4` |
| Phase name | LLM Authority Reviewer |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |
| Rollback status | `NOT_APPLIED`; P4 is additive, default-off, and has no migration. |

## Delivered

- Added bounded P4 authority-role proposals through `LLMProviderPort`, using only private candidate indices rather than document identity or benchmark information.
- Added deterministic hard validation for discovery state, provenance, scope, source binding, and status. Hard-filtered candidates are always `IRRELEVANT`.
- Preserved `NOT_RETRIEVED` and `QUARANTINED` as distinct states rather than conflating them with filtered candidates.
- Preserved a role proposal for an eligible governing candidate while assigning `CURRENT_EFFECT_UNVERIFIED` when current effect is not independently established.
- Added default-off deterministic fallback assigning only `BACKGROUND` to otherwise eligible candidates; it does not elevate authority.
- No legal-effect relation, Reviewed Legal Effects write, retrieval query, final evidence selection, citation, runtime activation, or legal conclusion was introduced.

## Files changed

- `src/legal_chatbot/legal_evidence/authority/__init__.py`
- `src/legal_chatbot/legal_evidence/authority/models.py`
- `src/legal_chatbot/legal_evidence/authority/parser.py`
- `src/legal_chatbot/legal_evidence/authority/service.py`
- `tests/unit/test_legal_authority_review.py`
- `docs/review/phases/P4-llm-authority-reviewer.md`
- `docs/review/phases/P4-llm-authority-reviewer.json`

## Tests and checks

| Command / scope | Result |
|---|---|
| P4 authority proposal/filter/fallback tests | `3 passed` |
| Full suite with `--import-mode=importlib` | `899 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `pip check` | pass |
| `git diff --check` | pass |

## Gate evaluation

P4 proposals are structured and bounded. Deterministic validation records a state for every candidate, preserves filter reasons, and rejects scope/source-binding conflicts before role acceptance. Tests prove a proposed `GOVERNING` role cannot survive a scope conflict and that non-retrieval is distinct from filter state. No benchmark marker or provider-specific adapter client appears in P4 source.

## Known limitations

- P4 is default-off and no live provider-quality assertion is made.
- Metadata is passed through a future reader boundary; PostgreSQL metadata hydration remains a later default-off adapter task.
- P4 makes no current-effect verification or legal relation conclusion.
- P4 engineering checks do not establish legal-answer correctness or the P12 legal-quality target.
