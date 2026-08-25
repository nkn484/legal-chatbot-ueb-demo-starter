# Authority, Completeness, and Applicability Remediation

## Evidence Basis

The independent reviewed scorecard identifies the three highest-impact failure
classes: direct-authority substitution, incomplete material evidence, and
unverified applicability/version conclusions. This plan does not use case IDs,
expected document identities, titles, or benchmark wording in production logic.

## Changes

1. A document is `DIRECT_AUTHORITY` only when a material unit has an explicit
   source binding that matches the immutable document source identity, the
   provenance is official fetch, and the version is latest-ingested. Otherwise
   it remains implementing/supporting evidence, not a governing authority.
2. A material unit is `SUPPORTED` only with a matching direct authority. Other
   retrieved evidence is `PARTIALLY_SUPPORTED`, triggering the bounded repair
   path or an explicit answer limitation.
3. Because reviewed legal effects are OFF, every quality-path answer receives a
   fixed applicability/version limitation. The system never represents a
   retrieved latest-ingested version as verified current legal effect.

## Evaluation

- run unit and import-boundary tests;
- run Set A C07 evaluation only after the generalized checks pass;
- compare outcome, direct-authority coverage, expected-identity coverage and
  provider failures against the prior candidate;
- preserve Set B/C retrieval invariants; do not use them as legal-answer score;
- submit the resulting workbook to independent legal review before a release
  decision.

## Keep/Rollback

Keep the implementation only when no unsupported unit is labeled supported,
provenance/citation invariants remain clean, default production flags remain
off, and the new run does not introduce a safety regression. It does not pass
the legal release target until independent review records `>=8.50` average and
`>=9/10` PASS.
