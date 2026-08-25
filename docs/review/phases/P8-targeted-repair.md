# Phase P8 - One Targeted Repair Retrieval

## Result

| Field | Value |
|---|---|
| Phase ID | `P8` |
| Phase name | One Targeted Repair Retrieval |
| Implementation status | `COMPLETE` |
| Gate status | `PASS` |
| Decision | `KEEP` |
| Next phase allowed | `YES` |

## Delivered

- Added one-shot, default-off targeted repair for the first partial/unsupported material sub-intent.
- Repair query remains memory-only and targets missing `GOVERNING` evidence rather than replaying the full question.
- `NOT_IN_CATALOG` and `QUARANTINED` stop without invoking the reader.
- Repair evidence must support the recorded target sub-intent; evidence merges once and coverage recomputes once.
- `repair_count` is bounded by the immutable request contract at one.

## Tests and checks

| Scope | Result |
|---|---|
| P8 repair/catalog/quarantine/privacy tests | `2 passed` |
| Full suite | `908 passed`, `39 skipped`, `1 non-failing OpenPyXL warning` |
| Ruff, compile, diff checks | pass |

## Gate evaluation

Repair has one bounded cycle, never repeats catalog/quarantine cases, and target query/evidence identifiers are excluded from public output. The P8 reader is default-off. No benchmark oracle, provider call, DB write, or loop is introduced.

## Known limitations

- A real targeted PostgreSQL reader remains a later adapter task.
- P8 improvement is deterministic-contract evidence only; legal quality remains unmeasured.
