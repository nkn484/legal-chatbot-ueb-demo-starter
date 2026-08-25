# Phase P3 - Broad Document Discovery

## Result

| Field | Value |
|---|---|
| Phase ID | `P3` |
| Phase name | Broad Document Discovery |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |
| Rollback status | `NOT_APPLIED`; P3 is additive, default-off, and has no migration. |

## Delivered

- Added a pure P3 discovery workspace with independent title/metadata, content FTS, and semantic-vector lane observations.
- Added a reader port and default-off service that executes one private query per material sub-intent, joins the bounded raw results, and advances request state only from `ANALYZED` to `DISCOVERED`.
- Collapsed candidates by the full immutable document/version/provenance identity before applying the configurable 15-30 document workspace limit.
- Preserved filter state and rejected an unverified-provenance candidate from `ELIGIBLE` admission.
- Kept final evidence selection explicitly `false`; no authority role, relation, clause evidence, citation, provider call, database write, runtime composition, or production flag activation was introduced.

## Files changed

- `src/legal_chatbot/legal_evidence/discovery/__init__.py`
- `src/legal_chatbot/legal_evidence/discovery/models.py`
- `src/legal_chatbot/legal_evidence/discovery/service.py`
- `tests/unit/test_legal_broad_discovery.py`
- `docs/review/phases/P3-broad-document-discovery.md`
- `docs/review/phases/P3-broad-document-discovery.json`

## Tests and checks

| Command / scope | Result |
|---|---|
| P3 lane/collapse/provenance/default-off tests | `5 passed` |
| Full suite with `--import-mode=importlib` | `896 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, `src` and `tests` | pass |
| Python compileall, `src/legal_chatbot` | pass |
| `pip check` | pass |
| `git diff --check` | pass |

## Gate evaluation

P3 lane observations retain lane, rank, score, query count, and elapsed time. Tests prove full-identity collapse occurs before the workspace limit, duplicate versions are absent from the workspace, unverified provenance cannot enter as `ELIGIBLE`, and the workspace cannot carry a final-evidence decision. The enabled service is isolated behind a reader port and the default service is disabled.

Candidate recall, lane contribution, PostgreSQL latency, and workspace size over a real corpus remain diagnostic-only until a configured P3 reader is composed in a later default-off profile. This does not change the P3 engineering gate because no runtime path is activated here.

## Known limitations

- The P3 reader port is not yet composed with PostgreSQL/embedding infrastructure; existing quality candidate readers remain available for a later adapter integration.
- The workspace preserves discovery state only. P4 will introduce bounded LLM authority proposals plus deterministic validation.
- P3 does not establish retrieval quality, legal authority, applicability, answer correctness, or the P12 legal-quality release target.
