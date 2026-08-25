# Phase P6 - Pinpoint Evidence Reader

## Result

| Field | Value |
|---|---|
| Phase ID | `P6` |
| Phase name | Pinpoint Evidence Reader |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |
| Rollback status | `NOT_APPLIED`; P6 is additive, default-off, and has no migration. |

## Delivered

- Added a default-off pinpoint reader port restricted to document versions that are both selected in an authority family and matched to the material sub-intent.
- Added bounded per-sub-intent evidence reads with a maximum of five retained units and no placeholder/padding behavior when fewer results exist.
- Preserved `EvidenceReference` document/version/provenance/chunk locator through every retained `EvidenceUnit`.
- Rejected reader output whose sub-intent differs from the request or whose document version falls outside the allowed authority family.
- Advanced enabled context only from `FAMILIES_RESOLVED` to `EVIDENCE_READ`; no broad-corpus fallback, citation write, authority decision, provider call, or runtime activation was introduced.

## Files changed

- `src/legal_chatbot/legal_evidence/pinpoint/__init__.py`
- `src/legal_chatbot/legal_evidence/pinpoint/models.py`
- `src/legal_chatbot/legal_evidence/pinpoint/service.py`
- `tests/unit/test_legal_pinpoint_evidence.py`
- `docs/review/phases/P6-pinpoint-evidence-reader.md`
- `docs/review/phases/P6-pinpoint-evidence-reader.json`

## Tests and checks

| Command / scope | Result |
|---|---|
| P6 family restriction/locator/provenance/no-padding tests | `2 passed` |
| Full suite with `--import-mode=importlib` | `904 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `git diff --check` | pass |

## Gate evaluation

Every retained test evidence unit maps to its one material sub-intent and an allowed family document version. Locator/provenance are mandatory through `EvidenceReference`; an out-of-family version fails closed. The configured maximum is five per sub-intent and the service does not pad missing units. Pinpoint-versus-flat retrieval quality remains diagnostic-only until a PostgreSQL reader adapter and pre-registered comparator are available.

## Known limitations

- The reader is a default-off port; a PostgreSQL clause/paragraph reader remains a later adapter task.
- P6 makes no completeness, authority, applicability, citation-release, answer, or legal-quality claim.
