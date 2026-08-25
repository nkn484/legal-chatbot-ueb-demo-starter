# Phase P11 - Independent Legal Reviewer

## Result

| Field | Value |
|---|---|
| Phase ID | `P11` |
| Phase name | Independent Legal Reviewer |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES - P12 evaluation only` |

## Delivered

- Added a default-off P11 reviewer under `legal_evidence/review` that receives the private draft, P10 claim map, exact P9-selected evidence pack, and coverage matrix through `LLMProviderPort`.
- Reviewer output is limited to `PASS|REVISE|PARTIAL|BLOCK` plus enumerated finding codes and existing zero-based claim, material-sub-intent, and evidence indices. It cannot return free-text law, document IDs, citations, or new evidence identifiers.
- Added a deterministic guard that rejects a PASS when a material `SOURCE_FACT` or `SUPPORTED_INTERPRETATION` claim has no matching selected evidence, or an unsupported/partial issue lacks a `LIMITATION` or `NEXT_CHECK` claim.
- Added an optional one-shot evidence-bound rewriter. It receives the same immutable selected evidence and is reviewed again once. A second `REVISE`, invalid rewrite, or reviewer failure fails closed to `BLOCK` or `PARTIAL`; a second rewrite is impossible by contract.
- A successful P11 result is labeled `P12_CANDIDATE_ONLY`. It is not legal release approval and does not establish legal quality.

## Tests and checks

| Scope | Result |
|---|---|
| P11 unit pack | `8 passed` |
| P11 + P10 + P1-P10 vertical-slice + M08 feature-gate regressions | `12 passed` |
| Full suite (`pytest --import-mode=importlib -q`) | `951 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff check/format for P11 files | pass |
| Compile check for P11 package | pass |

The default `pytest -q` command has pre-existing collection collisions for five duplicate test basenames across `tests/unit` and `tests/integration`. `--import-mode=importlib` isolates those names without modifying test configuration or caches.

## Gate evaluation

- Claim/evidence review: PASS. The strict schema and deterministic guard validate all reviewer indices against the exact P10 claim and P9 evidence counts.
- Unsupported material claim: PASS. A reviewer `PASS` cannot override a structural support failure.
- Rewrite bound: PASS. Exactly one rewrite may occur, followed by one re-review; `REWRITE_EXHAUSTED` blocks another rewrite.
- New evidence prevention: PASS. Out-of-pack reviewer evidence indices are rejected as invalid output, and the evidence reader must preserve exact selected unit order and identity.
- Release boundary: PASS. P11 emits only `P12_CANDIDATE_ONLY`; it has no release activation path, migration, retrieval path, registry write, or M08 runtime integration.

## Known limitations

- P11 remains default-off and is not wired into M08 while `LEGAL_CHAT_PIPELINE_ENABLED=false`.
- No live provider run was performed for P11. Existing provider structured-output reliability remains a separate runtime concern and is not masked by this gate.
- The current deterministic P10 diagnostic drafts remain inadequate for legal-quality release; P11 engineering PASS does not change the provisional `1.64/10`, `0/10 PASS`, `NO_GO_FOR_LEGAL_QUALITY` result.

## Engineering-versus-legal quality

P11 PASS validates only the reviewer/guard engineering objective. It does not establish answer correctness, citation integrity, retrieval recall, authority coverage, Set B stability, or the legal release target. Only P12 plus independent full-text legal review may establish `Average >= 8.50/10` and `PASS >= 9/10`.
