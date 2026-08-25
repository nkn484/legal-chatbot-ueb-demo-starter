# P5/P6 Corrective Diagnostic

Decision: `UPSTREAM_BLOCKED`

The Q10 forensic trace established that P5 retained all relevant authority
families for warning grounds and warning/dismissal process. P6 then recovered
10 real pinpoint evidence units after the family-scoped handoff and
dimension-aware query correction. The remaining dismissal-grounds gap is not a
P5 or P6 loss: P4 supplied zero eligible relevant candidates for that sub-intent.

| Case | P5 families | P5 budget prune | P6 evidence | Result |
| --- | --- | --- | --- | --- |
| Q10 | 3 | 0 | 10 | `UPSTREAM_AUTHORITY_GAP` remains for dismissal grounds. |
| Q05 | 15 | 2 | 15 | No family overflow; all P7 states supported. |
| Q06 | 11 | 0 | 20 | No regression; all P7 states supported. |

P2 remains deterministic fallback, P4 semantics remain frozen, P11 remains
OFF, and P3/P6/P8 use real PostgreSQL readers. No full Set A or midpoint legal
review workbook was run.
