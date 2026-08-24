# Prompt-03 Verification Plan

**Scope:** Gate-3: SYNTHETIC_SHADOW_VALIDATED documentation record. Gate-2 remains
`PASS_WITH_REMEDIATION`. Validation owner: orchestrator. This plan does not establish legal
truth or enable production.

Gate-2 evidence is DB head `0012`, four reviewed-registry tables with 0 rows, 727
unit+compose PASS, 3 PostgreSQL integration PASS, lifecycle PASS, Ruff PASS, and no
runtime/retrieval imports. See `prompt03-gate2-importer-runbook.md` for layer boundaries,
manual-snapshot policy, restricted-role requirements, and Gate-3 stop conditions.

Gate-3 evidence is 7 actual disposable scenarios with outcome counts of `SHADOW_DISABLED` 1,
`SHADOW_ELIGIBLE` 2, `SHADOW_SUPPRESSED_EVENT` 1, `SHADOW_UNRESOLVED` 1,
`SHADOW_CONFLICT` 1, and `SHADOW_INPUT_REJECTED` 1. Restricted role checks PASS;
retrieval/citation unchanged; the main database registry remains 0 rows; 733 unit+compose,
3 PostgreSQL integration, lifecycle, and Ruff PASS; diagnostics are temporary only.

## Claims, evidence owners, and budgets

| Claim | Evidence owner | Budget / acceptance evidence |
| --- | --- | --- |
| Gate-1 counts match the verified inventory | Orchestrator | Exact count comparison; no new query required. |
| Draft artifact is constrained and default-off | Orchestrator | JSON parse plus schema-shape lint; zero unknown keys in all modeled objects. |
| Importer preserves evidence identity | Future implementation owner | Gate-2 fixtures: endpoint source/external/snapshot/hash and basis provenance/locator all resolve or reject. |
| Registry cannot infer legal relationships | Future implementation owner | Gate-2 fixture suite: zero inferred records; only approved artifact relations accepted. |
| Runtime does not alter default behavior while disabled | Future runtime owner | Gate-3 fixed fixture suite: 100% disabled-mode suppression. |
| Shadow diagnostics stay bounded | Future runtime owner | Gate-3: only approved identifier/kind/family/revision/conflict fields; no raw content. |

Budgets are deliberately small: at most 100 family declarations and 1,000 relation
records per artifact in the draft; locator and note fields cap at 500 characters;
identifiers cap at 128 characters. Any larger load or vocabulary expansion needs separate
approval and a revised contract.

## Gate 2: schema and importer tests

1. Parse the draft JSON Schema and assert its `DRAFT_NOT_APPROVED-1` version and
   `DOCUMENTATION_ONLY_DEFAULT_OFF` profile state.
2. Validate a synthetic, non-legal fixture containing only placeholder identifiers and
   hashes. Confirm required endpoint, basis-version, provenance, locator, approval, and
   family fields are required.
3. Reject additional properties, malformed hash, unknown source, blank locator, missing
   immutable selector, unknown role, duplicate assertion identifier, and subject/object
   identity collision.
4. Reject `AMENDS`, `REPLACES`, `REPEALS`, temporal intervals, and every effect state
   other than `EFFECT_NOT_MODELED` in the initial profile.
5. Resolve valid synthetic selectors against a controlled test repository; reject absent
   source/external identities, version/hash mismatch, and absent provenance.
6. Verify an accepted import is atomic and append-only. Verify correction creates a
   successor assertion plus `CORRECTS`; revocation creates `REVOKES`; update/delete is
   denied.
7. Emit bounded conflict codes only; do not include raw artifact/document content in
   diagnostics.

### Gate-2 implementation status: PASS_WITH_REMEDIATION

Implemented a transactional, default-off importer and explicit CLI entry point. The importer
uses source/external/version-hash identity, strict transport provenance, and chunk locator
metadata only; it does not inspect chunk text. It has bounded code-only failures, atomic
idempotency/conflict handling, and append-only correction/revocation persistence. Validation
remains owned by the orchestrator and does not establish legal truth or enable runtime use.
Successful output reports inserted-row counts plus unique manual-snapshot and source-fetch basis
counts only. An `ALREADY_IMPORTED` output reports zero inserted-row and basis counts.

### Gate-3 shadow status: SYNTHETIC_SHADOW_VALIDATED

The Gate-3 evaluator is an explicit, default-disabled, read-only synthetic profile. It accepts
only server-owned import/family references and returns temporary aggregate diagnostics. It has no
runtime wiring and cannot change retrieval, ranking, citations, or user-visible output. Manual
snapshot evidence is limited to the `HASH_PINNED_PILOT_ALLOWED` synthetic/disposable policy and
retains a caveat; it makes no official-source or currentness claim. Disposable evaluation databases use restricted
importer and shadow roles, and the evaluation command retains no diagnostics file or relation data.

## Gate 3: runtime evaluation tests

1. Disabled default: a registry fixture has no effect on retrieval, ranking, citations,
   or response fields.
2. Shadow mode: an approved, current synthetic assertion produces only the approved
   relation kind, family identifier, registry revision, and diagnostic state.
3. Correction/revocation: a later approved event suppresses the superseded assertion.
4. Isolation: retrieved text, metadata labels, model output, and user content cannot
   create or modify a reviewed relation.
5. Ambiguity: duplicated normalized numbers do not select an endpoint; the stable
   source/external/snapshot/hash tuple is required.
6. Report aggregate pass/fail counts, disabled suppression rate, and bounded conflict-code
   distribution. Do not score or assert legal correctness.

## Required failure fixtures

- Unknown property, oversized identifier, URL-like locator, UUID-like identifier, or raw
  content field.
- Missing source/external identity, snapshot identifier, hash, provenance identifier, or
  pinpoint locator.
- Bad hash, endpoint version/hash disagreement, missing catalog/evidence dependency, or
  normalized-number-only endpoint.
- Unapproved source, role, relation kind, effect state, interval, or runtime-enable flag.
- Duplicate relation and an event that corrects itself, lacks a successor, or revokes with
  a successor.
- A family marked complete outside its declared scope, and a conflicting approved review.
- Untrusted input attempting to request a relation or modify output.

## No production enablement conditions

Gate 1 and its validator never enable production. Production remains prohibited unless all
of the following are explicitly approved: schema/migration implementation; reviewer and
approver authority; initial family scope and completeness language; locator/basis standard;
append-only correction/revocation procedure; Gate-2 and Gate-3 results; diagnostics and
user-output policy; source-acquisition limits; and a separate default-off-to-enabled rollout
decision. Legal correctness remains a reviewer responsibility, not a test result.
