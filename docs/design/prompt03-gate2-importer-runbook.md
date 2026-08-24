# Prompt-03 Gate-2 Importer / Gate-3 Shadow Runbook

**Status:** Gate-3: SYNTHETIC_SHADOW_VALIDATED. Gate-2 remains
`PASS_WITH_REMEDIATION`. This is an operational design record, not an authorization to enable
runtime behavior or import real legal-effect data. Validation owner: orchestrator.

## Evidence recorded

| Evidence | Result |
| --- | --- |
| Database head | `0012` |
| Reviewed-registry tables | four tables, 0 rows |
| Unit and compose checks | 727 unit+compose PASS |
| PostgreSQL integration checks | 3 PostgreSQL integration PASS |
| Lifecycle check | PASS |
| Ruff | PASS |
| Runtime/retrieval imports | none |

## Gate-3 synthetic-shadow evidence

| Evidence | Result |
| --- | --- |
| Disposable scenarios | 7 actual disposable scenarios |
| Outcome counts | `SHADOW_DISABLED` 1; `SHADOW_ELIGIBLE` 2; `SHADOW_SUPPRESSED_EVENT` 1; `SHADOW_UNRESOLVED` 1; `SHADOW_CONFLICT` 1; `SHADOW_INPUT_REJECTED` 1 |
| Restricted role checks | PASS: no UPDATE, no DELETE, not table owner, not superuser |
| Retrieval/citation behavior | retrieval/citation unchanged |
| Main database registry | 0 rows |
| Unit and compose checks | 733 unit+compose PASS |
| PostgreSQL integration checks | 3 PostgreSQL integration PASS |
| Lifecycle check | PASS |
| Ruff | PASS |
| Diagnostics | temporary diagnostics only |

No real relation record, document mapping, family mapping, or legal conclusion is recorded
by this runbook.

## Shadow outcome semantics

`SHADOW_ELIGIBLE` means only that structurally valid active reviewed assertions have strict
provenance and locator validity under the synthetic profile. It is **not** legal applicability,
authority, completeness, current effect, or answer eligibility.

`SHADOW_SUPPRESSED_EVENT` means selected-family assertions are suppressed by an event. The
evaluator does not follow or validate a successor in another import/family and does no
successor-based legal selection.

Manual/source basis counts are distinct validated basis-provenance counts only. They are not
an independent authority count or completeness proof. `HASH_PINNED_PILOT_ALLOWED` remains
synthetic/disposable only and never elevates evidence to official-source status.

## Enforcement layers

| Layer | Enforces | Does not establish |
| --- | --- | --- |
| JSON Schema | shape, enums, limits, and `additionalProperties` only | Cross-record semantics, database identity, legal correctness, or completeness. |
| Pydantic/parser | semantic cross-record rules, reviewer/approver independence, timestamp order, Unicode C*/URL note rejection, duplicate-key rejection, and size limits | Database resolution, stored-locator equality, authorized write access, or legal truth. |
| Importer | endpoint hash resolution, strict provenance/version linkage, stored locator match, active-duplicate checks, event checks, idempotency, and atomicity | Legal correctness or completeness. |
| Database | FKs, checks, `runtime_enabled=false`, and append-only UPDATE+DELETE triggers | Unauthorized INSERT prevention by itself, legal truth, or completeness. |

The DB does **not** prevent unauthorized INSERT by itself. Schema validation and parser
success likewise do not approve a legal relation.

## Importer-only write authority

Direct SQL/DML is unsupported and prohibited operationally. The only supported write path is
the approved CLI/importer command; it records `imported_by` for audit and emits content-free
diagnostics. Artifact access is restricted to authorized operators and reviewers. Output must
contain only counts, stable outcome codes, and approved diagnostic metadata; it must not emit
artifact text or evidence text.

For Gate 3, the runbook requires a separately approved restricted database role: INSERT only
on registry tables as needed, SELECT on evidence tables, no UPDATE, no DELETE, and neither
table-owner nor superuser capability. Actual role creation is deferred and separately
approved. This requirement does not grant the role or approve an import.

## Manual snapshot policy

`MANUAL_SNAPSHOT` is technically admissible for synthetic/disposable work only when immutable
hashes, strict provenance, a stored locator, and independent legal review/approval all
resolve. Every such result retains the `MANUAL_SNAPSHOT` caveat. It is never official-source
proof or currentness proof.

Before any non-synthetic family import, artifact approval must explicitly choose exactly one
policy: `HASH_PINNED_PILOT_ALLOWED` or `REFRESH_REQUIRED`. Gate 2 has no real artifact and
makes neither choice.

## Declared-complete boundary

`DECLARED_COMPLETE` applies only to an approved artifact's declared family scope. It does not
authorize retrieval filtering, answer eligibility, authority ranking, currentness claims,
global completeness claims, or user-visible legal effect. Those remain unavailable until Gate
3 and later approvals.

## Closure invariants

The profile remains default disabled. There is no environment/runtime composition, retrieval
import, user-visible field, real artifact, answer effect, retrieval effect, or citation effect.
Temporary diagnostics are not retained as a runtime feature.

## Final pre-real-artifact checklist

No next implementation is authorized until every item is separately approved.

- [ ] Exact family semantics and declared scope are approved for each family.
- [ ] Exact endpoint hashes, provenance, locators, and duplicate adjudication are approved.
- [ ] Named governance actors are approved for submission, review, approval, and import.
- [ ] Per-family manual policy and freshness decision are approved.
- [ ] Production role grants and importer-only DML authority are approved.
- [ ] Shadow integration references, diagnostic retention, and main database import approval
  are approved.
- [ ] No routing effects are approved until a later gate explicitly authorizes them.

## Historical Gate 3 entry checklist

Gate 3 uses synthetic fixtures only. Do not supply actual document identifiers, document
mapping, legal relation data, or source text.

- [ ] Confirm the shadow outcome-code set: `SHADOW_DISABLED`, `SHADOW_ELIGIBLE`,
  `SHADOW_SUPPRESSED_EVENT`, `SHADOW_UNRESOLVED`, `SHADOW_CONFLICT`, and
  `SHADOW_INPUT_REJECTED`.
- [ ] Approve generic synthetic family IDs and synthetic endpoint selectors only.
- [ ] Approve distinct synthetic importer-operator, reviewer, and approver IDs; reviewer and
  approver remain independent.
- [ ] Choose `HASH_PINNED_PILOT_ALLOWED` or `REFRESH_REQUIRED` for the synthetic/manual
  policy record; do not treat this as a non-synthetic approval.
- [ ] Approve diagnostic retention period, access roles, and content-free output fields.
- [ ] Confirm shadow-only operation: no retrieval filtering, ranking change, response change,
  citation change, or user-visible effect.
- [ ] Separately approve the restricted database-role design before any Gate-3 importer run.

## Gate 3 stop conditions

Stop and return to approval when a required selector cannot resolve, provenance/version or
stored locator differs, an active duplicate or prior event conflicts, diagnostics would expose
content, the restricted role is unavailable, or any outcome would leave shadow-only mode.
