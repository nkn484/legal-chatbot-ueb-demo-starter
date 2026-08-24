# Prompt-03 Gate-1 Inventory / Gate-2 Approved Artifact Contract

**Status:** Gate-3: SYNTHETIC_SHADOW_VALIDATED. Gate-2 remains
`PASS_WITH_REMEDIATION`. The approved artifact contract and synthetic shadow validation are
complete; no next implementation is authorized. This authorizes neither a migration, database
importer invocation, nor runtime use. The approved default-off schema is
`contracts/reviewed-legal-effects-v1.schema.json`; the Gate-1 draft remains historical.

The authoritative Gate-2 enforcement-layer and importer-authority boundaries are recorded in
`prompt03-gate2-importer-runbook.md`. In particular, parser success is not database
resolution; database checks do not prevent unauthorized INSERT by themselves; and
`DECLARED_COMPLETE` is only declared family-scope language. The Gate-3 closure boundaries and
pre-real-artifact checklist are recorded in `prompt03-gate2-importer-runbook.md`.

## Gate-2 approved decisions (authoritative)

- Artifact version is `reviewed-legal-effects-v1`; profile is
  `APPROVED_SCHEMA_DEFAULT_OFF`. The artifact has no runtime-enable field.
- The exact endpoint selector is `source_id`, `external_id`, `snapshot_sha256`, and
  `normalized_text_sha256`. This replaces the ambiguous Gate-1 `snapshot_id` proposal.
  The future importer must resolve both hashes against immutable `DocumentVersion` fields.
- `basis.provenance_id` is a canonical lowercase, hyphenated UUID matching
  `SourceProvenanceRecord.id`; it is not an opaque actor/relation/family identifier.
  Endpoint selectors and provenance UUIDs are controlled importer-boundary data. They are
  excluded from model `repr`, and parser errors expose stable codes only.
- Only `VBQPPL`, `VNU`, and `UEB`; `IMPLEMENTS`/`GOVERNS`;
  `EFFECT_NOT_MODELED`; and ARTICLE/CLAUSE/SECTION/PAGE locators are accepted.
- Artifact-wide approval has submitted, reviewed, and approved opaque actor IDs and ordered,
  timezone-aware timestamps. Roles are `LEGAL_REVIEWER` and independent
  `LEGAL_APPROVER`; reviewer and approver identities differ.
- Families remain generic declarations. They and relation records contain no document
  number, title, URL, raw source content, evaluation prompt, or evaluation answer content.
- Optional correction events inherit the artifact-wide approval. A `CORRECTS` event names a
  distinct successor relation; `REVOKES` has no successor. Event-local approval metadata is
  intentionally forbidden.
- Correction reason codes are restricted to the approved future DB enum:
  `ENDPOINT_NOT_FOUND`, `VERSION_HASH_MISMATCH`, `PROVENANCE_NOT_FOUND`,
  `LOCATOR_INVALID`, `DUPLICATE_ASSERTION`, `FAMILY_SCOPE_CONFLICT`,
  `REVIEW_DISAGREEMENT`, `SUPERSEDED_BY_REVIEW`, and `WITHDRAWN_BY_REVIEW`.
- An event `assertion_id` may identify a current-artifact relation or a prior-import DB
  assertion. Static schema and parser validation cannot resolve the latter. A `CORRECTS`
  successor must be a distinct relation declared in the current artifact; the future importer
  resolves the target and prior-event conflicts transactionally.
- Scope notes, pinpoint values, and reason notes reject every Unicode `C*` category in the
  parser, including format controls such as bidi marks. JSON Schema blocks C0/C1 controls but
  cannot fully express that Unicode-category policy; the parser is authoritative.
- Canonical compact sorted UTF-8 serialization is hashed by the future importer. An artifact
  never supplies its own trusted hash.
- This lane adds only frozen Pydantic parsing/canonicalization contracts and synthetic tests.
  Database tables, import implementation, migrations, and runtime behavior remain deferred.

## Historical Gate-1 proposal

The exploratory storage proposal below is retained for decision traceability only. Where it
conflicts with the approved Gate-2 section, the approved section controls; in particular,
`snapshot_id`, content-hash-only selectors, `OTHER_PINPOINT`, per-event approval metadata,
and artifact runtime flags are not part of the approved artifact contract.

## Options and recommendation

| Option | Benefit | Cost / risk |
| --- | --- | --- |
| A. Infer relations from corpus metadata | Fast | Unsafe with 22 number collisions and raw, unreviewed status. Reject. |
| B. Mutable relation row | Simple queries | Loses correction history and basis at the time of review. Reject. |
| C. Append-only reviewed registry | Auditable, reproducible, pins evidence | Requires review workflow. Recommend. |
| D. Full temporal/effect graph now | Covers later legal questions | Scope and correctness risk exceed current evidence. Defer. |

**Recommendation:** C with a small, reviewed initial prototype: `IMPLEMENTS` and
`GOVERNS` assertions only, no temporal selection. Every assertion is attached to stable
source/external endpoints, immutable version/hash evidence, provenance, and a precise
locator. No automated creation or inference is permitted.

## Proposed storage model (not implemented)

All identifiers below are application-generated opaque strings; no existing document,
version, provenance, catalog, or citation table is changed.

### `reviewed_legal_effect_import`

| Column | Type | Constraint |
| --- | --- | --- |
| `import_id` | `varchar(128)` | primary key |
| `artifact_hash` | `char(64)` | required, lowercase SHA-256 format |
| `schema_version` | `varchar(64)` | required |
| `submitted_at` | `timestamptz` | required |
| `submitted_by` | `varchar(128)` | required |
| `approved_at` | `timestamptz` | required |
| `approved_by` | `varchar(128)` | required |
| `approval_role` | `varchar(32)` | required; `LEGAL_APPROVER` |
| `imported_at` | `timestamptz` | required, default current timestamp |
| `imported_by` | `varchar(128)` | required |
| `runtime_enabled` | `boolean` | required, default `false`, check `false` for initial prototype |

Indexes: unique (`artifact_hash`); index (`approved_at`); index (`runtime_enabled`).

### `reviewed_legal_effect_family`

| Column | Type | Constraint |
| --- | --- | --- |
| `import_id` | `varchar(128)` | FK to import, required |
| `family_id` | `varchar(128)` | required |
| `completeness` | `varchar(32)` | `DECLARED_PARTIAL` or `DECLARED_COMPLETE` |
| `scope_note` | `varchar(500)` | required; no raw document content |
| `created_at` | `timestamptz` | required |

Primary key (`import_id`, `family_id`). Index (`family_id`, `import_id`).
`DECLARED_COMPLETE` means only that the approved artifact's stated family scope was
reviewed; it never means global legal completeness.

### `reviewed_legal_effect_assertion`

| Column | Type | Constraint |
| --- | --- | --- |
| `assertion_id` | `varchar(128)` | primary key |
| `import_id` | `varchar(128)` | FK to import, required |
| `family_id` | `varchar(128)` | required; composite FK to family |
| `subject_source_id` / `subject_external_id` | `varchar(32)` / `varchar(256)` | required; endpoint identity |
| `subject_snapshot_id` / `subject_content_sha256` | `varchar(128)` / `char(64)` | required; immutable version/hash selector |
| `object_source_id` / `object_external_id` | `varchar(32)` / `varchar(256)` | required; endpoint identity |
| `object_snapshot_id` / `object_content_sha256` | `varchar(128)` / `char(64)` | required; immutable version/hash selector |
| `relation_kind` | `varchar(32)` | required; initial check in (`IMPLEMENTS`, `GOVERNS`) |
| `effect_state` | `varchar(32)` | required; initial check = `EFFECT_NOT_MODELED` |
| `basis_source_id` / `basis_external_id` | `varchar(32)` / `varchar(256)` | required |
| `basis_snapshot_id` / `basis_content_sha256` | `varchar(128)` / `char(64)` | required |
| `basis_provenance_id` | `varchar(128)` | required; identifies `SourceProvenanceRecord` |
| `basis_locator_type` / `basis_locator_value` | `varchar(32)` / `varchar(500)` | required; locator is bounded, no URL required |
| `reviewed_by` / `reviewed_at` | `varchar(128)` / `timestamptz` | required |
| `approved_by` / `approved_at` | `varchar(128)` / `timestamptz` | required |
| `created_at` | `timestamptz` | required |

Checks: source IDs are one of the approved registry sources; all hash fields match
lowercase SHA-256; subject and object endpoint tuples differ; locator type is one of
`ARTICLE`, `CLAUSE`, `SECTION`, `PAGE`, `OTHER_PINPOINT`; locator value is nonblank;
review and approval timestamps are not later than `created_at`. Unique (`import_id`,
`assertion_id`). Indexes: (`subject_source_id`, `subject_external_id`),
(`object_source_id`, `object_external_id`), (`family_id`), (`relation_kind`), and
(`basis_provenance_id`). The importer resolves each endpoint against `LegalDocument`,
`DocumentVersion`, and `SourceProvenanceRecord` before insert; it must reject missing or
mismatched version/hash pairs.

### `reviewed_legal_effect_event`

| Column | Type | Constraint |
| --- | --- | --- |
| `event_id` | `varchar(128)` | primary key |
| `assertion_id` | `varchar(128)` | FK to assertion, required |
| `event_kind` | `varchar(32)` | `CORRECTS` or `REVOKES` |
| `successor_assertion_id` | `varchar(128)` | required for `CORRECTS`, null for `REVOKES` |
| `reason_code` | `varchar(64)` | required conflict/correction code |
| `reason_note` | `varchar(500)` | required |
| `reviewed_by` / `reviewed_at` | `varchar(128)` / `timestamptz` | required |
| `approved_by` / `approved_at` | `varchar(128)` / `timestamptz` | required |
| `created_at` | `timestamptz` | required |

Checks enforce the event shape above and prohibit self-successors. Indexes:
(`assertion_id`, `created_at`) and (`successor_assertion_id`). No update or delete is
permitted on imports, assertions, or events. A correction appends a replacement assertion
and a `CORRECTS` event; revocation appends a `REVOKES` event. Runtime may only use an
assertion with no later approved revocation/correction event.

## Vocabulary, conflicts, and audit

Initial relation vocabulary: `IMPLEMENTS`, `GOVERNS`. Initial effect state:
`EFFECT_NOT_MODELED`. Conflicts/correction reason codes: `ENDPOINT_NOT_FOUND`,
`VERSION_HASH_MISMATCH`, `PROVENANCE_NOT_FOUND`, `LOCATOR_INVALID`,
`DUPLICATE_ASSERTION`, `FAMILY_SCOPE_CONFLICT`, `REVIEW_DISAGREEMENT`,
`SUPERSEDED_BY_REVIEW`, and `WITHDRAWN_BY_REVIEW`.

The future-only vocabulary, requiring explicit approval and schema/migration revision, is
`AMENDS`, `REPLACES`, `REPEALS`, `PARTIALLY_REPEALS` plus effect states and start/end
intervals. They are not accepted by the draft artifact or recommended prototype.

Audit is supplied by immutable import payload/hash, submit/review/approval/import actor and
time fields, endpoint and basis version/hash, provenance identifier, pinpoint locator, and
append-only events. The database should record rejected import diagnostics separately from
accepted records without retaining raw artifact content beyond approved retention policy.

## Importer workflow

1. Receive a schema-valid, approved artifact while `runtime_enabled=false`.
2. Validate source/external endpoint identity, snapshot identifier, hash, provenance, and
   locator against existing immutable evidence.
3. Validate declared family completeness, roles, duplicate assertions, and allowed
   vocabulary; emit only bounded conflict codes.
4. Persist one import, its families, assertions, and any events atomically; never mutate
   prior accepted rows.
5. Produce a diagnostic summary without raw content. Enabling a runtime flag is a separate
   approved deployment decision, not an importer default.

## Runtime stages and default flag

| Stage | Behavior |
| --- | --- |
| Gate 1 (this pack) | Documentation only; no storage or runtime change. |
| Gate 2 | Schema/import validation in isolation; `runtime_enabled=false`. |
| Gate 3 | Shadow evaluation of reviewed output fields; still default-off. |
| Production enablement | Only after explicit approval, evidence gates, and a separately approved rollout. |

The default is off. Retrieval, ranking, citations, and response generation continue to
operate without this registry until production enablement conditions are met.

## Test and verification gates

Gate 2: validate artifact shape; reject unknown keys, URL/raw-content fields, unknown
source IDs, non-immutable selectors, missing provenance/locator, unapproved roles,
deferred kinds, invalid state, duplicate endpoint assertions, invalid corrections, and
hash mismatch. Verify append-only permissions and atomic rollback.

Gate 3: with a fixed reviewed fixture, verify disabled mode produces no relation/effect
output; shadow mode emits only identifiers, kind, declared family, review revision, and
diagnostic code; revoked/corrected assertions are suppressed; unreviewed retrieved text
cannot change output. Evaluate only aggregate metrics and failure fixtures, not legal truth.

## YAGNI boundary

In the recommended initial prototype, add only the four proposed registry tables, the
two relation kinds, `EFFECT_NOT_MODELED`, immutable endpoint/basis selectors, family
declaration, and append-only corrections/revocations. Defer temporal intervals, legal
status calculation, automatic extraction, authority ranking, broad completeness claims,
AMENDS/REPLACES/REPEALS behavior, graph traversal, backfill, and user-facing legal-effect
claims until separately approved.
