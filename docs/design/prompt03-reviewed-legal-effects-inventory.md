# Prompt-03 Gate-1: Reviewed Legal Effects Inventory

**Status:** read-only design evidence; not a legal review and not a legal-correctness claim.  
**Database observation:** head `0011`.

**Gate-2 status:** the artifact parser contract is approved default-off only. It does not
add reviewed records, persistence, importer behavior, runtime output, or legal conclusions.

## Observed corpus and metadata

| Observation | Exact count / result |
| --- | ---: |
| Legal documents | 670 |
| Document versions | 672 |
| Documents with one version | 669 |
| Documents with three ingestion versions | 1 |
| Latest rows with issue date | 661 / 670 |
| Latest rows with effective date | 86 / 670 |
| Latest rows with source-updated timestamp | 1 / 670 |
| Latest rows with legal status | 669 / 670 |
| Latest rows with normalized number | 669 / 670 |
| Latest rows with title | 669 / 670 |
| Normalized-number keys spanning distinct document identities | 22 |
| Relation, legal-effect, amendment, or supersession tables | 0 |

The presence of raw status metadata is not a reviewed conclusion about legal effect. A
normalized number is not an identity key: the 22 collisions require endpoint selection
by source and external identity plus an immutable snapshot/hash.

## Provenance and status observations

| Provenance | Count |
| --- | ---: |
| `manual_snapshot` / `STRICT_TLS` | 668 |
| `source_fetch` / `STRICT_TLS` | 2 |

Raw latest-status distribution (metadata only; not reviewed legal effect):

| Source | Active-ish | Expired | Other |
| --- | ---: | ---: | --- |
| UEB | 243 `Còn hiệu lực` | 67 `Hết hiệu lực` | — |
| VNU | 226 | 45 | — |
| VBQPPL | 77 active | 10 expired | 1 partially expired |

## Capability matrix

| Capability | Current evidence | Gate-1 conclusion |
| --- | --- | --- |
| Stable document identity | `LegalDocument(source_id, external_id)` | Available; required for every reviewed endpoint. |
| Immutable evidence version | immutable `DocumentVersion` identifier and hashes | Available; pin review basis to a version/hash. |
| Acquisition provenance | `SourceProvenanceRecord` | Available; record provenance and locator, but do not elevate it to authority. |
| Catalog linkage | catalog row and child citations | Available for lookup/evidence linkage. |
| Relation assertion | no relation table | Not available; reviewed registry required. |
| Effect / time selection | no effect, amendment, supersession tables | Not available; defer temporal behavior. |
| Number-only matching | 22 ambiguous keys | Unsafe; prohibited for relation endpoints. |
| Automatic legal inference | no reviewed dataset | Prohibited. |

Registry priority remains rollout order, not legal authority.

## Expert-family implications

All 26 distinct expert expected document families have at least one indexed linked entry,
across 29 case occurrences. This supports a narrow reviewed-family prototype without
adding acquisition coverage first. It does **not** establish that every family member,
duplicate catalog identity, relation, status, amendment, or legal effect is correct.
The reviewed artifact must name families generically and declare their completeness
scope; it must not copy evaluation prompts, answers, or document-number mappings.

## Blockers and limitations

### Acquisition blockers

- 668 of 670 observations are manual snapshots; freshness and completeness require an
  approved acquisition plan before they can support a broader temporal registry.
- Only 1 of 670 latest rows has `source_updated_at`; source recency cannot be broadly
  measured from current metadata.
- Duplicate catalog identities and 22 normalized-number collisions require adjudication
  through stable endpoint selectors, not catalog or number heuristics.

### Policy blockers

- Approval is required for the reviewed family scope, reviewer and approver authority,
  locator/basis standard, correction process, and allowed runtime output.
- No reviewed relation records exist. No system may infer IMPLEMENTS, GOVERNS, amendment,
  replacement, repeal, or applicability from titles, text, dates, retrieval rank, or raw
  metadata.
- Temporal selection, legal-effect intervals, and amendment/supersession logic are out
  of the recommended initial prototype.

### Privacy and provenance limits

This pack contains aggregate counts and generic selectors only. It intentionally excludes
raw document text, chunks, user content, raw channel identifiers, credentials, evaluation
prompt text, and evaluation answer content. `manual_snapshot` identifies an acquisition
method, not official-source provenance or legal authority. `STRICT_TLS` records transport
handling, not source authenticity, legal validity, or review quality.
