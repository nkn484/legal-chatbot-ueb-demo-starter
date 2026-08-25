# P5/P6 Corrective Review

Final decision: `UPSTREAM_BLOCKED`

## Root Cause

The initial Q10 trace was `MULTIPLE_GAPS`: two P6 losses and one upstream P4
authority gap. The P5/P6 corrections removed the P6 losses:

- P5 now prioritizes cross-sub-intent authority coverage before applying its
  existing fifteen-family boundary, without source-level role ranking.
- P5 consolidates versions that share a stable legal-document identity.
- P6 accepts P4-relevant assessments inside P5-retained families even when the
  original P3 candidate had not been marked for that same sub-intent.
- P6 uses bounded dimension-aware OR FTS terms inside those families only.

The follow-up Q10 trace returned 10 P6 evidence units. `DISMISSAL_GROUNDS`
still has zero eligible P4 candidates, so it is explicitly
`UPSTREAM_AUTHORITY_GAP`; P2/P4 are frozen in this milestone and were not
changed to mask that result.

## Safety and Verification

- P2 Oracle, P2 gate, P2 decomposition, P4 role semantics, P7-P11, and full
  Set A were not changed or run.
- Q05 stayed within 15 P5 families with two explicit budget-pruned candidates.
- Q06 completed without regression.
- Full regression: `930 passed, 39 skipped, 1 warning`.
- Ruff, compileall, and dependency checks passed.
- PostgreSQL document/chunk counts did not change; no unexpected DB write was
  observed.

This decision does not establish legal quality, release readiness, or
P1-P10 `FLOW_PASS`.
