# Prompt-03 Approval Checklist

**Status:** Gate-3: SYNTHETIC_SHADOW_VALIDATED. Gate-2 remains
`PASS_WITH_REMEDIATION`. This checklist records closure decisions; it does not approve runtime
behavior, real imports, or legal truth.

All choices preserve default-off runtime behavior until a separate rollout.

## Final pre-real-artifact approvals required

- [ ] Confirm synthetic fixtures only: generic family IDs and endpoint selectors, with no
  actual document mapping or legal relation data.
- [ ] Approve the required shadow outcome codes: `SHADOW_DISABLED`, `SHADOW_ELIGIBLE`,
  `SHADOW_SUPPRESSED_EVENT`, `SHADOW_UNRESOLVED`, `SHADOW_CONFLICT`, and
  `SHADOW_INPUT_REJECTED`.
- [ ] Name distinct synthetic importer-operator, reviewer, and approver IDs.
- [ ] Select the manual policy record: `HASH_PINNED_PILOT_ALLOWED` or `REFRESH_REQUIRED`.
- [ ] Approve diagnostic retention, access roles, and content-free output fields.
- [ ] Confirm shadow-only operation and no retrieval, ranking, response, citation, or
  user-visible effect change.
- [ ] Approve the restricted database-role design separately; role creation remains deferred.
- [ ] Approve exact family semantics and declared scope for each family.
- [ ] Approve exact endpoint hashes, provenance, locators, and duplicate adjudication.
- [ ] Approve named governance actors and per-family manual policy/freshness decisions.
- [ ] Approve shadow integration references, diagnostic retention, and main database import.
- [ ] Confirm that no routing effects are approved until a later gate.

| Decision required | Recommended answer | Alternatives |
| --- | --- | --- |
| Tables | Four append-only tables: import, family, assertion, event | Delay all storage; a mutable table is not recommended. |
| Initial relation kinds | `IMPLEMENTS`, `GOVERNS` only | Add kinds only in a revised approved contract. |
| Temporal scope | Defer intervals and temporal selection | Approve a separately designed temporal model now. |
| Initial family prototype | Narrow reviewed subset of the 26 indexed expert families; declare `DECLARED_PARTIAL` unless scope is expressly reviewed | One named pilot family; broader reviewed set. |
| Reviewer role | `LEGAL_REVIEWER` submits/reviews | A named organizational role with equivalent authority. |
| Approver role | independent `LEGAL_APPROVER` | Designated legal governance role; self-approval is not recommended. |
| Endpoint standard | source ID + external ID + immutable snapshot ID + SHA-256 | No number-only or catalog-only selectors. |
| Basis and locator standard | immutable basis version/hash + `SourceProvenanceRecord` ID + article/clause/section/page/other pinpoint | Require a more restrictive pinpoint taxonomy. |
| Correction workflow | append replacement assertion and approved `CORRECTS`/`REVOKES` event | Do not permit mutable correction. |
| Diagnostic fields | bounded conflict code, relation ID, family ID, revision/state only | Further restrict to conflict code and revision. |
| User-visible output | no legal-effect output in initial disabled profile; shadow diagnostics only | Approve carefully worded reviewed-relation labels after Gate 3. |
| Acquisition blocker treatment | retain manual-snapshot caveat and require stable evidence resolution | Fund source refresh/completeness work before broader scope. |
| Duplicate identities | require exact stable endpoint identity; route conflicts to review | No automatic number-based deduplication. |
| Runtime flag | `false` by default and separately enabled | Keep permanently documentation-only. |

## Historical pre-Gate-2 approvals

- [ ] Accept/reject the four-table append-only model.
- [ ] Select the allowed relation vocabulary and confirm deferred kinds remain disabled.
- [ ] Select temporal scope: defer (recommended) or approve a separate temporal design.
- [ ] Define the initial reviewed family set and its `DECLARED_PARTIAL`/`DECLARED_COMPLETE`
  contract without embedding evaluation mappings.
- [ ] Name authorized reviewer and independent approver roles.
- [ ] Approve endpoint, basis-version, provenance, and pinpoint-locator requirements.
- [ ] Approve correction/revocation authority, reason codes, retention, and audit access.
- [ ] Approve bounded diagnostics and whether any user-visible field is permitted.
- [ ] Decide whether manual-snapshot freshness, duplicate identities, and missing source
  timestamps block the selected family scope.
- [x] Gate-2 completed as PASS_WITH_REMEDIATION; this does not authorize Gate 3.

## Exact remaining pre-real-artifact questions

1. Which generic synthetic family IDs and synthetic endpoint selectors are approved for the
   shadow fixture, with no actual document mapping?
2. Which distinct synthetic importer-operator, reviewer, and approver IDs are approved?
3. Which manual policy record is approved: `HASH_PINNED_PILOT_ALLOWED` or
   `REFRESH_REQUIRED`?
4. What diagnostic retention period, access roles, and content-free output fields are approved?
5. Is shadow-only confirmed with no retrieval, ranking, response, citation, or user-visible
   effect change?
6. Is the restricted database-role design approved for Gate 3, while role creation remains
   deferred?
