# Authority, Completeness, and Applicability Remediation Result

## Scope

This run implements only the reviewed failure classes: direct-authority
selection, material evidence completeness, and applicability/version discipline.
No benchmark-specific production rule, corpus expansion, or latency tuning was
introduced.

## Implementation

1. Direct authority now requires official fetched provenance, latest-ingested
   version, `Còn hiệu lực` status metadata, document type and issuing authority,
   and no conflict with an explicit per-unit source binding.
2. A unit without a matching direct authority remains partial and is eligible for
   only one targeted repair; it cannot silently become supported from a similar
   supporting document.
3. Every quality-path answer now carries a server-enforced limitation that
   applicability/current legal effect has not been independently verified.
4. A multi-unit merge defect in query-specific supporting semantic diagnostics
   was fixed without changing identity/provenance collapse rules.

## Set A Result

| Metric | Hybrid candidate | Remediation C07 |
|---|---:|---:|
| Grounded answers | 10/10 | 10/10 |
| Provider failures | 0 | 0 |
| Citation count | 3/case | 3/case |
| Unique document versions | mixed/duplicated | 3 in every case |
| Expected-document-hit cases | 5 | 5 |
| Mean source coverage | 58.33% | 43.33% |
| Applicability/version limitation | prompt-only | 10/10 server-enforced |
| Real route p95 | 26,033.26 ms | 63,686.20 ms |

Catalog blockers remain two `NOT_IN_CATALOG` identities and one quarantined
identity. These are disclosed evidence gaps; the system does not infer a
replacement authority.

## Technical Decision

The remediation is retained for its generalized safety properties: no duplicate
document-version evidence in final selection and mandatory applicability/version
qualification. It is **not** a release winner: expected-hit coverage did not
improve, source coverage declined, and its provider p95 is materially higher.

**Technical decision: `HOLD_PENDING_LEGAL_REVIEW`.** The release target remains
`NOT_MEASURED` until the independent reviewer re-scores the remediated answer
workbook against the frozen rubric. The candidate cannot be called `>=8.50` or
`>=9/10 PASS` from technical metrics.

## Reviewer Inputs

- `docs/evals/stress-2026-08-25-authority-completeness-applicability.xlsx`
- `docs/legal-review-scorecard-reviewed-2026-08-25.md`
- `docs/review/release-dossier-2026-08-25.md`
- `docs/review/legal-review-scorecard-2026-08-25.md`
