# Legal Evidence Investigation Pipeline - Master Implementation Plan

## Document control

- Status: `MASTER_PLAN_COMPLETE = TRUE`
- Authorization: `IMPLEMENTATION_AUTHORIZED_BY_MASTER_PROMPT = TRUE`
- Scope: complete implementation plan for phases P1-P17. The master prompt authorizes sequential implementation after this corrective planning task; this corrective task itself remains documentation-only and does not start P1.
- Controlling principle: `LLM_PROPOSES -> EVIDENCE_VERIFIES -> LLM_SYNTHESIZES -> REVIEWER_CHALLENGES -> DETERMINISTIC_GUARD_RELEASES`.
- Release target: Set A average `>= 8.50/10`, Set A `>= 9/10 PASS`, Set C zero material safety regression, resolvable material citations, and zero fabricated legal authority.
- Preserved boundaries: `LLMProviderPort`, `LegalSourcePort`, and `ChannelPort` are never bypassed. Provider/source/channel implementation details remain inside adapters.
- Rollout rule: all new behavior is default `OFF`; Reviewed Legal Effects remains `OFF` unless separately approved; no gate result enables production.
- Workflow rule: implement exactly one phase at a time, test it, evaluate its gate, and write both phase reports. On `PASS`, automatically continue to the next phase. On failure, rework the same phase until it passes or a true blocker exists. Do not ask for routine approval between phases.

## Repository review and baseline

### Inspected surfaces

The review covered the API and runtime composition (`api/app.py`, `runtime/m08.py`), chat orchestration and prompts, provider contracts, retrieval contracts and services, PostgreSQL lexical/hybrid/quality repositories, semantic and reranking ports, document/version/provenance/citation ORM models, conversation boundaries, Reviewed Legal Effects, feature configuration, diagnostics/evaluation tooling, unit and integration tests, and the latest material in `docs/diagnostics`, `docs/evals`, `docs/review`, and `docs/plans`.

The worktree is intentionally treated as non-clean prior work. Existing uncommitted quality-pipeline edits and generated evaluation artifacts must be preserved and reconciled; phase rollback means reverting only that phase's attributable delta, never resetting the repository or deleting prior evidence.

### Reusable implementation

- `retrieval/quality_repair`: immutable Pydantic contracts, deterministic analyzer, candidate collapse/fusion, authority-role assessment, coverage matrix, one-shot repair, dynamic evidence budget, structured evidence pack, structural claim validation, and privacy-safe traces.
- `documents/quality_candidate_reader.py` and `quality_retrieval_pipeline.py`: independent title/content-FTS/semantic reads, document-version collapse, provenance hydration, and bounded read-only execution.
- `documents/quality_retrieval_repository.py`: opt-in persistence adapter and request-local `quality_context` seam.
- `documents/orm.py`, `grounding_evidence.py`, and `citation_resolver.py`: immutable document/version/chunk/provenance chain and persisted citation resolution.
- `chat/quality_prompt.py` and `chat/service.py`: structured pack prompt seam, provider-neutral generation through `LLMProviderPort`, citation re-resolution, and fail-closed answer path.
- `diagnostics/evaluation`: C01-C08 ablation records, run manifest, evaluation-only orchestrator, and benchmark-leakage scanner.
- `legal_effects`: approved artifact/import/shadow machinery with evidence locators and read-only evaluation; it remains default disabled and is not mutated by this milestone.
- Existing tests establish import boundaries, privacy exclusion, retrieval/citation invariants, provider fallback behavior, PostgreSQL read paths, and feature-default safety.

### Measured baseline and current weaknesses

| Measurement point | Average | PASS count | Role in this milestone |
|---|---:|---:|---|
| ORIGINAL BASELINE | `5.49/10` | `4/10 PASS` | Historical starting baseline; preserve for before/after reporting. |
| PREVIOUS INDEPENDENT REVIEW | `5.85/10` | `2/10 PASS` | Historical provider-healthy Set A review; decision was `NO_GO`. |
| LATEST REMEDIATED LEGAL REVIEW | `5.81/10` | `4/10 PASS` | Current comparison point for all future quality improvement. |
| RELEASE TARGET | `>= 8.50/10` | `>= 9/10 PASS` | Controlling legal-quality release threshold. |

- The latest authority/completeness/applicability remediation retained useful safety controls but remains below the legal target. Future quality deltas must compare first against `5.81/10` and `4/10 PASS`, while also retaining both earlier historical measurements.
- Broad semantic discovery can find substantially more expected identities than final selection, while fixed final top-3 drops material authorities.
- Natural title/content FTS contribution has been weak or zero in accepted diagnostics; this must be observed and improved by generalized behavior, not benchmark literals.
- Corpus state includes `NOT_IN_CATALOG` and `QUARANTINED` governing documents. Neither state may be repaired by inference or repeated search.
- Current authority assessment is mostly deterministic and metadata-based. It does not yet represent bounded LLM role proposals, explicit hard/soft validation states, authority families, or evidence-verified relation hints.
- Current analysis is deterministic. The target requires a bounded LLM analyzer with a deterministic fallback and no benchmark leakage.
- Existing evidence is selected at document/chunk candidate time; the target requires authority selection first and issue-specific pinpoint reading inside chosen families.
- Coverage exists per analyzer unit but lacks the full target vocabulary and explicit role/tier/version/relation gap model.
- The answer path has a structured pack but no independent reviewer pass, one-rewrite limit, or deterministic release decision over reviewer output.
- Current technical groundedness and citation integrity are valuable but cannot establish legal correctness, authority, applicability, or completeness.

### Technical debt to resolve incrementally

1. `retrieval/quality_repair` currently owns concepts broader than retrieval. Do not perform a disruptive rename. Introduce a pure `legal_evidence` domain/application package and adapt existing quality-repair contracts incrementally behind compatibility mappings.
2. `RetrievalResult.quality_context` is typed as `object`; replace its quality-path use with an explicit request-context contract while preserving the public retrieval result behavior.
3. Existing `DIRECT_AUTHORITY` naming can be mistaken for verified governing authority. During migration map it to a candidate/proposal state until deterministic validation completes.
4. Current currentness metadata (`latest_ingested`, textual legal status) is not proof of current legal effect. Preserve it only as Category A metadata and expose applicability qualification.
5. Evaluation artifacts contain different historical thresholds. The controlling milestone threshold is the higher master target above; older thresholds remain historical evidence only.

## Target architecture

```text
Channel / Conversation
        |
        v
LegalEvidenceInvestigationService  (request-scoped orchestration)
        |
        +--> QuestionAnalyzerPort --> LLMProviderPort --> provider adapter
        |          `--> deterministic fallback
        +--> DiscoveryPort --> PostgreSQL title / content FTS / vector adapters
        +--> AuthorityReviewPort --> LLMProviderPort --> proposal only
        |          `--> deterministic AuthorityValidator
        +--> RelationInvestigationPort --> proposal only
        |          `--> RelationEvidenceVerifier
        +--> PinpointEvidencePort --> bounded reads inside selected versions
        +--> CompletenessReviewPort --> LLM proposal + deterministic coverage
        +--> one TargetedRepairPort call at most
        +--> coverage-first EvidenceSelector
        +--> AnswerComposerPort --> LLMProviderPort
        +--> LegalAnswerReviewerPort --> LLMProviderPort
        `--> deterministic ReleaseGuard
                   |
                   v
           Chat result + resolvable citations
```

`LegalCaseContext` is immutable request state. Each stage returns a new copy. User-derived question, analyzer text, repair text, raw evidence text, prompts, and provider payloads are memory-only and excluded from public serialization and ordinary logs. Persisted records contain only approved identifiers, bounded codes/counts, evidence references, and citation/provenance facts.

## Legal truth and data contracts

### Category ownership

- Category A, deterministic facts: document/version/chunk/provenance IDs, source, issuer/type/status metadata as ingested, dates/numbers, catalog/quarantine state, locators, exact text references, and verified database relationships. Only repositories/evidence verifiers populate these.
- Category B, LLM proposals: question decomposition, candidate authority roles, relation hints, likely missing evidence, draft interpretation, and review findings. Every proposal carries stage, schema version, bounded confidence/reason codes, and `proposal_only=true`; it cannot mutate Category A.
- Category C, verified legal interpretations: usable only when deterministic evidence links, provenance, validation rules, and applicability qualification all pass. The release guard rejects silent promotion from A or B.

### Canonical request state

P1 will define `LegalCaseContext` with: `request_id`, `question_analysis`, `sub_intents`, `candidate_documents`, `authority_candidates`, `authority_families`, `relation_hints`, `evidence_units`, `coverage_matrix`, `limitations`, `answer_draft`, `review_result`, `repair_count`, and stage status. It will include the requested enums, with compatibility mapping from existing names:

- `AuthorityRole`: `GOVERNING`, `IMPLEMENTING`, `SUPPLEMENTARY`, `BACKGROUND`, `IRRELEVANT`.
- `AuthorityState`: `ELIGIBLE`, `FILTERED_PROVENANCE`, `FILTERED_SCOPE`, `FILTERED_STATUS`, `FILTERED_SOURCE_BINDING`, `NOT_RETRIEVED`, `NOT_IN_CATALOG`, `QUARANTINED`.
- `ApplicabilityState`: `VERIFIED`, `METADATA_CURRENT`, `CURRENT_EFFECT_UNVERIFIED`, `CONFLICT`, `UNKNOWN`.
- `CoverageState`: `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED`, `CONFLICT`.
- `RelationType`: `AMENDS`, `REPLACES`, `REPEALS`, `IMPLEMENTS`, `GOVERNS`.
- `RelationVerification`: `HINT_ONLY`, `EVIDENCE_VERIFIED`, `REVIEWED`, `REJECTED`.

No `LLMProviderPort` output may construct an evidence-verified relation or a `VERIFIED` applicability state. Those constructors remain internal to deterministic validators.

## Architectural decision records

### ADR-LEI-001: LLM reasoning is bounded by stage-specific schemas

LLMs are useful for decomposition, relevance, authority-role hypotheses, missing-evidence review, synthesis, and adversarial review. Each call receives the minimum required bounded context and returns strict provider-neutral JSON. This improves semantic understanding without granting database or legal-truth write authority.

### ADR-LEI-002: LLM output remains proposal-only

Provider text is untrusted until parsed and validated. Proposal models cannot populate verified fields, evidence IDs not supplied in input, source metadata, document numbers, or legal effects. Provider failure or invalid output selects a deterministic fallback or a fail-closed stage result.

### ADR-LEI-003: Legal-effect relationships require evidence verification

Date, issuer, title similarity, or semantic proximity do not prove amendment, repeal, replacement, implementation, or governance. A verified relation requires a resolvable document/version/provenance reference and an explicit clause locator whose text supports the relation pattern. Conflicts remain explicit. Reviewed Legal Effects is read-only/default-off and receives no automatic writes.

### ADR-LEI-004: Broad discovery and final evidence selection are separate

Discovery optimizes recall over approximately 15-30 unique versions and tolerates noise. Final selection optimizes coverage and authority after validation. This directly addresses the measured broad-to-final loss and prevents a fixed similarity cutoff from acting as a legal decision.

### ADR-LEI-005: Authority-family resolution precedes pinpoint reading

Legal rules often require a base instrument, amendment, and implementation guidance. Investigating family relations before clause retrieval avoids treating isolated chunks as complete authority and bounds later reading to selected versions.

### ADR-LEI-006: Pinpoint reading follows authority selection

The same document supports different questions through different clauses. Focused within-document queries produce 2-5 evidence units per sub-intent where justified, each with a resolvable locator and provenance chain. Arbitrary broad chunks never flow directly to answer synthesis.

### ADR-LEI-007: Completeness is per material sub-intent

Question-level groundedness hides partial failure. Coverage is computed for every sub-intent and tracks governing authority, implementing need, source/catalog state, applicability, relation conflict, and clause evidence. No aggregate can promote partial coverage to supported.

### ADR-LEI-008: Final selection is coverage-first

For C05+, select 3-6 evidence units only when available and justified. First cover governing authority for each material sub-intent, then necessary implementation, verified relation/version evidence, and supplementary support. Similar documents for one issue cannot exhaust the budget.

### ADR-LEI-009: Independent review is a separate bounded pass

The composer can omit or overstate even with good evidence. A logically separate prompt reviews the draft against the same evidence pack and may request one rewrite without adding law or triggering retrieval. The deterministic guard owns release.

### ADR-LEI-010: Evaluation oracles are isolated

Historical expected IDs are retrieval-regression data only. The legal-review oracle assesses current authority families from corpus evidence. Neither oracle is available to production analysis, retrieval, ranking, repair, synthesis, or feature selection.

## Dependency graph

```text
P1 Contracts
  -> P2 LLM Question Analyzer
  -> P3 Broad Discovery
  -> P4 Authority Reviewer
  -> P5 Authority Family / Relation Investigation
  -> P6 Pinpoint Evidence Reader
  -> P7 Completeness Reviewer
  -> P8 Targeted Repair
  -> P9 Coverage-First Evidence Selection
  -> P10 Answer Composer
  -> P11 Independent Legal Reviewer
  -> P12 Quality Evaluation
  -> P13 Regression Strategy
  -> P14 Observability
  -> P15 Feature Rollout
  -> P16 Security / Full Testing
  -> P17 Final Release Dossier
```

## Common phase controls

- Every phase produces `docs/review/phases/Pxx-<slug>.md` and `docs/review/phases/Pxx-<slug>.json` with `phase_id`, `phase_name`, `implementation_status`, `files_changed`, tests run/passed/failed, gate status, known limitations, rollback status, decision (`KEEP|REWORK|ROLLBACK`), and `next_phase_allowed`.
- A phase starts from the latest accepted state. Its report records the pre-phase commit/worktree fingerprint and attributable file list so rollback does not destroy user changes.
- Unit tests run on every phase. Relevant integration/boundary/security tests scale with the changed surface. Full regression runs at P1, P11, P12, P16, and before P17; narrower phases run their impacted suites plus invariant tests.
- Migrations are additive and reversible where possible. Any destructive migration stops for explicit approval.
- Logs use predefined safe keys only. Raw question/query/evidence/prompt/provider/channel/user content is prohibited.
- All external I/O is async, bounded by configured timeout/retry limits, and accessed through ports.

## COMMON QUALITY GATE DEFINITIONS

These definitions are frozen before phase implementation and apply wherever the named behavior is introduced or re-evaluated:

| Gate measure | Required result |
|---|---|
| Analyzer material sub-intent agreement on Set B | `>= 90%`, measured as paraphrases whose material sub-intent set matches the independently annotated parent set under the frozen evaluator normalization. |
| Maximum material sub-intents | `<= 4` per request. |
| Repair retrieval | `<= 1` cycle per request. |
| Answer rewrite | `<= 1` cycle per request. |
| C05+ final evidence | `3-6` eligible evidence units when at least three eligible units exist; fewer than three may be returned only when fewer than three are eligible. |
| Evidence padding | `0`; every selected unit must support a material sub-intent, necessary authority role, or verified relation/version qualification. |
| Set C material safety failures | `0`. |
| Fabricated legal authority | `0`. |
| Invalid or unresolvable material citations | `0`. |
| Benchmark leakage | `0` findings in production paths. |
| Unexpected database writes | `0`. |

Retrieval recall, lane contribution, pinpoint quality, latency, source coverage, and generalized recovery deltas are diagnostic/report-only unless a phase explicitly names a justified frozen threshold. Before a phase uses any non-numeric comparison for a gate, its phase report protocol must pre-register the dataset, comparator, metric, direction of improvement, non-inferiority constraints, and keep/rollback rule before the phase run. Results cannot be used to define or revise that rule after measurement.

## Engineering gate versus legal quality gate

`A Phase Gate PASS validates only the engineering objective of that phase.`

P1 PASS through P11 PASS DO NOT establish legal quality success. `ANSWER_GROUNDED`, citation integrity, retrieval recall, source coverage, test count, or latency DO NOT establish the legal release target. The Coding Agent must never report the overall milestone as successful merely because engineering gates pass.

Only P12 plus independent full-text legal review may establish both:

```text
Average >= 8.50 / 10
PASS >= 9 / 10
```

P13-P17 may validate regression protection, observability, rollout safety, security, reproducibility, and dossier completeness, but they cannot replace or override the P12 independent legal score.

## P1 - Domain contracts and request state

- Objective and weakness: introduce one explicit request-level context and legal-truth type system; current quality state is split across analyzer, selection, coverage, retrieval result, and prompt pack.
- Rationale: later stages cannot be safely gated without immutable stage ownership and explicit proposal/verified states.
- Scope: add pure contracts, stage transitions, compatibility mappings from existing quality-repair models, privacy-safe serializers, and constructors that restrict verified states. Out of scope: retrieval, provider calls, persistence schema, runtime activation, and legal-effect decisions.
- Architecture/files: add `src/legal_chatbot/legal_evidence/{__init__.py,models.py,context.py,transitions.py,ports.py}`; adapt only necessary exports in `retrieval/quality_repair`; add `tests/unit/test_legal_case_context.py`, `test_legal_truth_transitions.py`, and `test_legal_case_privacy.py`.
- Reuse: `_FrozenContract`, `DocumentIdentity`, analyzer units, candidate roles, coverage and evidence-pack concepts, `ResolvedCitation`, and provenance enums.
- Data contracts: canonical models/enums listed above; stage revisions are immutable; raw/private fields use `exclude=True`, `repr=False`; public serialization emits codes/counts only.
- LLM vs deterministic: no LLM responsibility. Deterministic validators own all construction and A/B/C transition rules.
- Security/failure modes: reject extra fields, duplicate IDs, missing provenance, verified relations without evidence locators, oversized collections, raw text serialization, and illegal stage regression.
- Migration/flags: no DB migration; no feature flag change; runtime behavior remains identical.
- Tests: schema/validation, serialization and repr privacy, forbidden state promotion, compatibility mapping, import boundaries, existing unit/integration regression.
- Observability: none beyond safe validation reason codes; do not log context payloads.
- Gate P1: all contracts/type validation and privacy tests pass, illegal promotions fail closed, no behavior becomes enabled, and existing suite remains green.
- Rollback: remove new pure package/tests and compatibility exports only.
- Expected impact: no direct score change; enables traceable implementation without legal-truth ambiguity.

## P2 - LLM legal question analyzer

- Objective and weakness: produce stable structured analysis for up to four material sub-intents; current analyzer is deterministic and limited for nuanced legal phrasing.
- Rationale: semantic decomposition is a suitable LLM task, while legal conclusions and expected identities are not.
- Scope: bounded current question, bounded conversation summary/recent turns, and known organization context; strict JSON proposal; deterministic existing analyzer as failure fallback. Out of scope: retrieval, document selection, source calls, legal conclusions, and benchmark IDs.
- Architecture/files: add `legal_evidence/analyzer/{models.py,prompt.py,parser.py,service.py}` implementing `LegalQuestionAnalyzerPort`; compose through `LLMProviderPort`; preserve `retrieval/quality_repair/analyzer.py` as fallback. Add focused unit tests and fake-provider integration test.
- Data contracts: main intent, actor, action/event, explicit time, topics, ambiguity, `<=4` sub-intents, preferred source/authority tiers as proposals, and retrieval concepts. Prohibit document IDs/numbers unless explicitly present in user input.
- LLM vs deterministic: LLM proposes analysis; parser enforces schema/bounds and protected-identity drift rules; fallback deterministically derives units; server assigns opaque IDs.
- Security/failure modes: prompt injection in user/context text, invalid JSON, timeout, too many units, provider-supplied authority identities, unstable paraphrases, and context overflow all fail to fallback.
- Migration/flags: no DB migration; `legal_llm_analyzer` default `OFF`; profile owns activation.
- Tests: schemas/parser, prompt separation, fallback for timeout/invalid response, conversation bounds, paraphrase Set B stability, no Q01-Q10/expected-ID leakage, port/import boundaries.
- Observability: provider outcome code, fallback used, sub-intent count, ambiguity code, duration; no raw content.
- Gate P2: valid bounded output, maximum four material sub-intents, fallback succeeds for every injected provider failure case, Set B material sub-intent agreement is `>=90%` under the frozen common definition, and benchmark leakage findings are `0`.
- Rollback: disable/remove analyzer adapter and retain deterministic analyzer.
- Expected impact: better issue coverage and repair targeting; no authority claim improvement by itself.

## P3 - Broad document discovery

- Objective and weakness: expose a 15-30 unique-version investigation workspace before authority decisions; current final budgets and candidate cutoffs lose material authorities.
- Rationale: discovery recall and final precision are different optimization problems.
- Scope: independent title/metadata, content FTS, and semantic vector lanes; per-unit queries; full identity/provenance hydration; collapse before workspace budget; lane contribution traces. Out of scope: final evidence selection, authority truth, relations, and answer generation.
- Architecture/files: extend `documents/quality_candidate_reader.py`, `quality_retrieval_pipeline.py`, and pure candidate models; add `legal_evidence/discovery/service.py`; keep SQL in adapters. Preserve existing lexical/hybrid repositories for legacy profiles.
- Data contracts: `CandidateDocument` with identity, provenance, catalog/quarantine state, per-lane ranks/scores, matched sub-intents, and discovery eligibility. Scores never imply authority.
- LLM vs deterministic: no LLM ranking decision; analyzer concepts are private inputs; repository determines factual metadata and eligibility.
- Security/failure modes: query injection, untrusted metadata, duplicate versions consuming budget, inaccessible/planned sources, quarantine leakage, semantic failure, and partial lane timeout. Fail closed or degrade to healthy lanes with explicit trace.
- Migration/flags: no expected DB change; additive indexes only if measured and separately approved; capability belongs to default-off profiles.
- Tests: document-collapse identity equality, independent lane observability, provenance preservation, read-only transaction, timeout/degradation, 15-30 workspace bounds, no premature top-3.
- Observability: lane counts/timing, unique versions, collapse ratio, filtered states, workspace size; no query text.
- Gate P3: every enabled lane emits count/rank/timing diagnostics, duplicate document versions in the investigation workspace are `0`, invalid provenance candidates admitted are `0`, and no final-evidence decision is applied. Recall, lane contribution, workspace size within the planned 15-30 range, and latency are diagnostic/report-only in P3; they do not independently fail the phase without a separately justified threshold pre-registered before execution.
- Rollback: route profile to existing candidate reader and remove only new orchestration.
- Expected impact: raises investigation recall and makes missing versus filtered documents distinguishable.

## P4 - LLM authority reviewer

- Objective and weakness: propose authority roles per sub-intent while preventing similar/supporting documents from substituting for governing authority.
- Rationale: authority relevance needs semantic reasoning, but eligibility and legal truth require deterministic facts.
- Scope: bounded candidate metadata and safe excerpts; structured role proposals; deterministic hard filters and soft qualifications. Out of scope: relation/current-effect verification and final evidence selection.
- Architecture/files: add `legal_evidence/authority/{models.py,prompt.py,parser.py,reviewer.py,validator.py}`; reuse and adapt `quality_repair/candidate_roles.py`.
- Data contracts: proposal role/reason per candidate/sub-intent; validated `AuthorityCandidate` with role, `AuthorityState`, `ApplicabilityState`, hard-filter codes, and soft limitations. `NOT_RETRIEVED` remains distinct from all filtered states.
- LLM vs deterministic: LLM proposes role/scope relevance. Validator owns provenance, identity, quarantine, explicit scope/source-binding/status conflicts and prevents rejected candidates from governing status.
- Security/failure modes: invented metadata, source priority treated as authority, program-specific scope generalized, currentness overstated, unsupported governing promotion, and provider failure. Invalid proposals degrade to deterministic conservative roles.
- Migration/flags: no DB migration; `legal_authority_reviewer` default `OFF`.
- Tests: schema/fallback, every hard/soft filter, source/scope conflicts, manual provenance, `CURRENT_EFFECT_UNVERIFIED`, no supporting substitution, no benchmark leakage.
- Observability: proposed role counts, validated role counts, filter reasons, filtered-direct-authority rate; identifiers remain request-private.
- Gate P4: structured proposals, deterministic filters, traceable reasons, scope conflicts never governing, and no conflation of absence/filtering.
- Rollback: disable reviewer and use conservative deterministic role mapping.
- Expected impact: reduces irrelevant-authority grounding and improves authority dimension without asserting current effect.

## P5 - Authority family and relation investigation

- Objective and weakness: represent base/amending/replacing/repealing/implementing/governing relationships with explicit verification; current retrieval treats documents mostly in isolation.
- Rationale: authority completeness and applicability depend on families, but relation truth cannot come from similarity or chronology.
- Scope: form provisional families, request LLM relation hints, search explicit relation clauses, validate locators/provenance, and represent conflicts. Out of scope: automatic registry writes, full current-effect modeling, or enabling Reviewed Legal Effects.
- Architecture/files: add `legal_evidence/relations/{models.py,prompt.py,parser.py,service.py,verifier.py}` and `documents/relation_evidence_repository.py`; reuse `legal_effects.validation.locator_matches` and read-only models where compatible.
- Data contracts: `AuthorityFamily`, `RelationHint`, evidence reference, verification state, conflict set, and family completeness. Hints remain `HINT_ONLY`; `EVIDENCE_VERIFIED` requires exact document/version/chunk/provenance and locator.
- LLM vs deterministic: LLM proposes possible relations and search concepts; verifier matches explicit legal-effect language in retrieved evidence and validates endpoints/provenance. Human-reviewed registry data, if later enabled, is a separate `REVIEWED` source.
- Security/failure modes: date/title/issuer inference, malicious clause instructions, reversed endpoints, missing locator, conflicting metadata, unsupported relation type, and registry mutation attempts.
- Migration/flags: preferably none; any persistence is request-trace only and additive. `legal_relation_investigator` default `OFF`; Reviewed Legal Effects remains `OFF` and read-only.
- Tests: hint isolation, explicit-evidence verification, locator resolution, conflicts, no automatic write, registry-off invariants, endpoint/provenance tampering.
- Observability: family/hint/verified/conflict counts and safe reason codes.
- Gate P5: hints are separate from facts, every verified relation resolves to evidence, conflicts remain explicit, and no registry mutation occurs.
- Rollback: discard request-local family/relation layer and retain independent documents.
- Expected impact: improves version/authority reasoning and prevents unsafe temporal inference.

## P6 - Pinpoint evidence reader

- Objective and weakness: retrieve issue-specific clauses inside selected authority families; current broad chunks can flow too directly into final evidence.
- Rationale: document selection answers “where to look,” not “which clause supports this issue.”
- Scope: focused per-sub-intent queries restricted to selected document versions; retain 2-5 useful units where justified; resolve exact locators/content references. Out of scope: unrestricted corpus discovery, final global budget, synthesis, and relation promotion.
- Architecture/files: add `legal_evidence/evidence/{models.py,pinpoint_service.py,ports.py}` and `documents/pinpoint_evidence_repository.py`; reuse chunks, embeddings, FTS query helpers, grounding and citation resolvers.
- Data contracts: `EvidenceUnit` contains opaque unit ID, document/version/chunk, source/provenance, locator, content reference, supported sub-intent, validated authority role, relation reference if any, and evidence quality state.
- LLM vs deterministic: LLM may propose focused concepts but cannot supply IDs/locators; repository searches only allowed versions; deterministic checks deduplicate, validate scope and resolve citation chain.
- Security/failure modes: arbitrary cross-document search, evidence padding, unresolved locators, duplicate clauses, prompt-like document text, missing embeddings, and oversized text. Content remains untrusted data.
- Migration/flags: no destructive migration; additive locator indexes only if measured. `legal_pinpoint_reader` default `OFF`.
- Tests: version restriction, per-issue differentiation, 2-5 bound without padding, locator/provenance resolution, malicious evidence isolation, read-only PostgreSQL integration, flat-chunk comparator.
- Observability: per-sub-intent evidence count, locator resolution rate, duplicate suppression, lane timings.
- Gate P6: every retained evidence unit maps to a material sub-intent and selected authority family, invalid or unresolvable material locators/citations are `0`, provenance-chain failures are `0`, and evidence padding is `0`. Pinpoint-versus-flat retrieval quality is reported using a pre-registered dataset, comparator, metric, and direction; it is diagnostic/report-only until a justified numeric threshold is frozen before execution.
- Rollback: use existing selected chunks under legacy profile; new profiles stay off.
- Expected impact: improves claim traceability, correctness, and reviewability.

## P7 - Evidence completeness review

- Objective and weakness: decide coverage independently for every material sub-intent; current coverage is structural but lacks bounded semantic review of missing roles/clauses.
- Rationale: evidence completeness is a matrix, not a question-level boolean.
- Scope: deterministic matrix plus bounded LLM proposal identifying missing governing/implementing/source/relation/clause evidence; reconcile without silent promotion. Out of scope: retrieval repair execution and answer writing.
- Architecture/files: add `legal_evidence/completeness/{models.py,prompt.py,parser.py,reviewer.py,reconciler.py}`; adapt `quality_repair/coverage.py`.
- Data contracts: each row records `CoverageState`, governing present, implementing needed/present, applicability state, relation conflict, source/catalog state, missing role/tier/clause codes, and supporting evidence IDs.
- LLM vs deterministic: LLM proposes omissions/conflicts; deterministic reconciler owns final state based on verified evidence. LLM may downgrade or flag review but cannot promote partial/unsupported to supported.
- Security/failure modes: aggregate promotion, fabricated missing identity, ignoring quarantine, conflict suppression, reviewer output overflow, or provider failure. Fallback is deterministic coverage.
- Migration/flags: no DB migration; `legal_completeness_reviewer` default `OFF`.
- Tests: all four states, multi-intent mixed state, governing absence, implementing need, conflict, provider fallback, monotonic no-promotion rule, trace privacy.
- Observability: coverage distribution, governing coverage ratio, missing-role/tier counts, conflict count.
- Gate P7: every sub-intent has traceable state, governing absence is explicit, and no partial/unsupported row becomes supported without new verified evidence.
- Rollback: use deterministic matrix only.
- Expected impact: directly addresses completeness failures and provides safe repair targets.

## P8 - One targeted repair retrieval

- Objective and weakness: perform at most one focused read for a recorded material gap; current repair contracts exist but do not cover the full authority-family/pinpoint model.
- Rationale: targeted recovery is useful, while loops and replaying the entire question create latency, privacy, and benchmark-tuning risk.
- Scope: select one highest-priority repair target `(sub-intent, missing role/tier)`, issue one bounded discovery/pinpoint pass, merge verified results, and recompute coverage once. Out of scope: repeated cycles, reranker-enabled repair unless profile explicitly permits it, corpus ingestion, quarantine recovery, and expected IDs.
- Architecture/files: add `legal_evidence/repair/{models.py,planner.py,service.py}`; adapt `quality_repair/repair.py`; invoke existing discovery/pinpoint ports.
- Data contracts: `RepairPlan` with opaque unit, missing class/role/tier, memory-only concepts, round=`1`; `RepairResult` with candidate/evidence counts, stop reason, and updated context.
- LLM vs deterministic: completeness proposal may inform the gap class; deterministic priority and bounds choose the target; no LLM generates document identities.
- Security/failure modes: loops, whole-question replay, raw repair persistence/logging, `NOT_IN_CATALOG` retries, quarantine use, source access escalation, and uncontrolled provider calls.
- Migration/flags: none; `legal_targeted_repair` default `OFF`; profile enforces maximum one.
- Tests: one-cycle invariant, exact gap targeting, no-op for catalog/quarantine/unavailable states, memory-only serialization, recompute once, no benchmark oracle, read-only DB behavior.
- Observability: repair executed, target class/role/tier code, candidate/evidence delta, stop reason, duration; no text.
- Gate P8: no loop, privacy preserved, repair improves the targeted row or terminates cleanly, and other rows do not regress silently.
- Rollback: disable repair; retain pre-repair coverage and limitations.
- Expected impact: recovers missing direct evidence without broad latency explosion.

## P9 - Coverage-first final evidence selection

- Objective and weakness: choose final evidence by legal coverage rather than global similarity/fixed top-3.
- Rationale: multi-part questions need distinct governing and implementing evidence across issues.
- Scope: C05+ final selection of 3-6 evidence units when eligible; coverage-first allocation, family diversity, verified relation evidence, no padding. Out of scope: synthesis, new retrieval, or LLM ranking.
- Architecture/files: add `legal_evidence/selection/{models.py,selector.py}`; adapt `quality_repair/evidence_budget.py`; keep existing C01-C04 fixed-three compatibility.
- Data contracts: `FinalEvidenceSelection` records ordered evidence IDs, covered sub-intents, role allocation, selection reasons, unresolved gaps, and justified target count.
- LLM vs deterministic: no LLM decision. Deterministic lexicographic policy prioritizes governing coverage per sub-intent, necessary implementation, verified relation/version evidence, then supplementary support; scores only break ties inside equal legal priority.
- Security/failure modes: one issue consumes all slots, supporting substitution, duplicate family padding, unverified relation prioritization, fewer than three eligible items, or more than six.
- Migration/flags: none; `legal_dynamic_evidence` default `OFF`; profile controls C05+.
- Tests: mixed sub-intents, family/role ordering, direct-authority preservation, no padding, 3-6 bounds, scarcity behavior, Q6-class generalized fixture, deterministic ordering.
- Observability: selected count, coverage ratio, role counts, family diversity, candidate-to-final loss.
- Gate P9: selection covers material issues before redundant evidence, blocks supporting-only substitution, and justifies every evidence count.
- Rollback: revert new profiles to existing fixed-three selector; flags remain off.
- Expected impact: addresses the dominant final-evidence cutoff and completeness failures.

## P10 - Structured legal answer composer

- Objective and weakness: synthesize from a structured Legal Evidence Pack with per-issue authority, coverage, applicability, and limitations; current prompt support is partial and answer claims are not explicitly typed.
- Rationale: flat chunks encourage omission and overgeneralization.
- Scope: build bounded composer prompt, strict output schema, material claims with evidence references, explicit unresolved issues, and article/paragraph citations. Out of scope: reviewer adjudication, new evidence, or release activation.
- Architecture/files: add `legal_evidence/composition/{models.py,prompt.py,parser.py,service.py}`; adapt `chat/quality_prompt.py`, `chat/service.py`, and evidence-pack contracts while preserving normal chat behavior.
- Data contracts: conclusion, per-sub-intent analysis, claim type (`SOURCE_FACT|SUPPORTED_INTERPRETATION|LIMITATION|NEXT_CHECK`), evidence-unit IDs, draft prose, and citation map. Provider output cannot add evidence identifiers.
- LLM vs deterministic: LLM composes only from supplied pack; parser validates claim/evidence references; structural validator and citation resolver reject unsupported/missing links and over-limit output.
- Security/failure modes: prompt injection in evidence, fabricated authority/locator, exact-case applicability overstatement, omitted unsupported unit, invalid JSON, provider timeout, and answer size overflow.
- Migration/flags: none; composer active only as part of an approved default-off strategy profile.
- Tests: all material units answered/resolved, fabricated reference rejection, limitation propagation, exact-case qualification, citation resolution, six-evidence compatibility, provider failure/refusal path, untrusted-data prompt separation.
- Observability: draft outcome, claim count/type distribution, unresolved unit count, citation validation outcome, provider timing.
- Gate P10: every material unit is answered or explicitly unresolved, citations resolve, and no unsupported authority/effect/applicability claim is released as draft.
- Rollback: route to existing grounded prompt/service under legacy profile.
- Expected impact: improves correctness, completeness, and claim-level traceability.

## P11 - Independent legal reviewer

- Objective and weakness: challenge the draft against the same evidence before release; no independent model pass currently exists.
- Rationale: a second, logically distinct pass can identify omissions and overclaims, but must not become a new evidence source.
- Scope: reviewer prompt, strict `PASS|REVISE|PARTIAL|BLOCK`, claim-level findings, one rewrite maximum using identical evidence, and deterministic release guard. Out of scope: retrieval, relation creation, registry writes, and more than one rewrite.
- Architecture/files: add `legal_evidence/review/{models.py,prompt.py,parser.py,service.py,release_guard.py}` and compose through `LLMProviderPort` in application/runtime layer.
- Data contracts: review decision, claim IDs, finding codes, required qualifications, rewrite instructions bounded to existing evidence, rewrite count, and final release outcome/reason.
- LLM vs deterministic: reviewer proposes findings/corrections; parser blocks new evidence IDs; composer may rewrite once; guard enforces evidence identity equality, structural validation, unresolved/conflict policy, and rewrite bound.
- Security/failure modes: reviewer invents law, removes limitations, changes evidence, provider collusion/prompt injection, endless revise, or reviewer failure. Failure defaults to `PARTIAL/BLOCK` according to deterministic coverage.
- Migration/flags: none; `legal_answer_reviewer` default `OFF` and enabled only with the full coherent profile.
- Tests: each decision, unsupported claim cannot pass, same-evidence rewrite, max one, new-law rejection, fallback/block, deterministic guard, full regression.
- Observability: review decision, findings count, unsupported claim rate, revision rate, final guard outcome; no draft/evidence text.
- Gate P11: unsupported material claims cannot silently pass, reviewer cannot add evidence, rewrite count is at most one, and guard deterministically owns release.
- Rollback: disable reviewer profile and retain composer draft path only for non-release evaluation.
- Expected impact: reduces unsupported inference and improves qualification discipline.

## P12 - Quality evaluation

- Objective and weakness: measure legal quality independently rather than infer it from groundedness, citations, recall, or tests.
- Rationale: engineering metrics and legal-review scores answer different questions.
- Scope: freeze Set A (10), Set B (`>=30` paraphrases), Set C (`>=20` controls), two separate oracles, C01-C08 ablation, run manifest, blinded full-text legal review, and leakage scan. Out of scope: production enablement and benchmark-driven code changes.
- Architecture/files: extend `diagnostics/evaluation/{orchestrator.py,ablation.py,leakage.py,run_manifest.py}` and evaluation scripts; write only P12 result artifacts named in P17 when measured.
- Data contracts: retrieval regression record, legal-review record under frozen 4.0/2.5/2.5/1.0 rubric, Set B stability, Set C invariants, configuration/corpus/provider hashes, and `MEASURED|NOT_MEASURED` states.
- LLM vs deterministic: production LLMs never see oracles. Qualified independent reviewers establish legal score; deterministic tooling validates manifests, aggregates, hashes, invariants, and leakage.
- Security/failure modes: oracle leakage, adaptive holdout use, invented scores, missing manifest fields, unblinded review, raw-content export, and using historical expected IDs as current legal truth.
- Migration/flags: none; all evaluated profiles remain off.
- Tests: evaluator contracts, oracle isolation, hash/manifest validation, leakage scanner, aggregation, Set B/C rules, artifact privacy.
- Observability: evaluation artifacts only; no runtime behavior change.
- Gate P12: independent full-text legal review is complete; Set B analyzer agreement is `>=90%`; Set C material safety failures are `0`; fabricated legal authority is `0`; invalid or unresolvable material citations are `0`; benchmark leakage findings are `0`. Report the legal target as met only when Set A average is `>=8.50/10` and `>=9/10` cases pass. An engineering P12 gate may otherwise record `PASS_WITH_LEGAL_TARGET_NOT_MET` only as evaluation-pipeline correctness, never as legal-quality success.
- Rollback: evaluation code/artifacts are retained as evidence; no runtime delta to roll back.
- Expected impact: produces credible quality evidence and identifies generalized remediation classes.

## P13 - Regression protection

- Objective and weakness: protect positive cases and generalized recovery classes across exact and paraphrased wording.
- Rationale: a fix that improves one benchmark but violates the frozen positive-case, paraphrase, or safety regression rule must be rejected.
- Scope: regression fixtures for positive Q05/Q07/Q09 classes and authority-recovery Q01/Q02/Q06/Q08/Q10 classes, expressed as sanitized behavior classes rather than production literals; Set B confirmations. Out of scope: case-specific runtime branches.
- Architecture/files: extend evaluation fixtures/contracts and add unit/integration regression suites; production source remains oracle-free.
- Data contracts: behavior class, expected invariant, minimum/maximum delta, source of truth, and observed result; expected IDs remain evaluator-only.
- LLM vs deterministic: LLM outputs are evaluated, never configured from cases. Deterministic leakage and regression checks enforce separation.
- Security/failure modes: case IDs/literals in production, generalized fix accepted from one exact question, positive-case regression, or paraphrase instability.
- Migration/flags: none.
- Tests: positive cases, recovery classes, Set B variants, static leakage scan, feature-off legacy regression.
- Observability: regression class pass/fail and aggregate deltas only.
- Gate P13: before execution, freeze the positive-case and recovery-class datasets, metrics, direction, non-inferiority bounds, and keep/rollback rule. The measured run must satisfy that frozen rule, Set B analyzer agreement must remain `>=90%`, Set C material safety failures must remain `0`, and benchmark leakage findings must remain `0`. Recovery and positive-case deltas remain diagnostic/report-only when no independently justified numeric threshold is available.
- Rollback: revert only the generalized remediation under review; preserve negative evaluation evidence.
- Expected impact: stabilizes gains and guards against benchmark overfitting.

## P14 - Observability

- Objective and weakness: expose stage behavior without prohibited content; current safe logs do not cover the complete investigation flow.
- Rationale: gates and operations need traceability, but raw legal queries/evidence are sensitive and untrusted.
- Scope: add the ten specified event types and aggregate metrics; extend allowlisted JSON logging keys. Out of scope: full distributed tracing and behavior-changing metrics.
- Architecture/files: add `legal_evidence/observability.py`; extend `core/logging.py` allowlist and stage services' code/count emission.
- Data contracts: event name, request-safe correlation ID, stage/schema/profile version, counts, durations, enums, and outcome codes. No raw question/query/prompt/evidence/answer/user/channel/provider payload.
- LLM vs deterministic: LLM content is never logged; deterministic stage wrappers emit safe summaries.
- Security/failure modes: accidental model dump logging, identifiers leaking, high-cardinality values, logging changing error behavior, and raw exception text.
- Migration/flags: no DB migration; metrics passive and profile-independent where safe.
- Tests: allowlist, prohibited-field scan, repr/model-dump privacy, event schema, exception sanitization, behavior equivalence with logging on/off.
- Observability: `LEGAL_ANALYSIS_COMPLETED`, authority proposal/filter, family/relation, pinpoint, coverage, repair, and review events; requested aggregate metrics.
- Gate P14: traces are useful and privacy-safe, sensitive text is absent, and instrumentation does not alter answers.
- Rollback: remove new emissions/keys without affecting stage outputs.
- Expected impact: faster diagnosis and auditable gate evidence; no direct legal score claim.

## P15 - Feature flags and rollout

- Objective and weakness: provide reproducible coherent profiles and straightforward rollback; current quality switches do not cover all new stages.
- Rationale: independent flags can create unsafe combinations; profile-level validation prevents partial pipelines.
- Scope: introduce named logical capabilities, coherent profiles, dependency validation, default-off runtime composition, and explicit release-approval requirement. Out of scope: production activation.
- Architecture/files: extend `retrieval/config.py`, `chat/config.py`, `runtime/m08.py`, and strategy materialization; preferably expose one profile selector plus derived read-only capabilities.
- Data contracts: profile ID/version and capabilities: analyzer, authority reviewer, relation investigator, pinpoint reader, completeness reviewer, targeted repair, dynamic evidence, answer reviewer; invalid combinations fail construction.
- LLM vs deterministic: configuration only controls stage availability; it never alters truth rules or bypasses validators.
- Security/failure modes: hidden enablement, environment alias drift, partial dependency activation, Reviewed Legal Effects coupling, legacy planner collision, or enablement after tests.
- Migration/flags: all new defaults `False`; Reviewed Legal Effects `OFF`; no DB migration.
- Tests: default config, profile reproducibility, dependency matrix, environment aliases, legacy behavior, rollback, no hidden activation, runtime construction failures.
- Observability: active profile/version and capability booleans only.
- Gate P15: default path unchanged/safe, profiles reproduce exactly, invalid combinations fail closed, rollback is one profile change, and no release activation occurs.
- Rollback: set profile off and retain dormant code.
- Expected impact: limits blast radius and makes evaluation/release repeatable.

## P16 - Security and full testing

- Objective and weakness: prove the complete pipeline preserves boundaries, provenance, read-only behavior, and untrusted-data isolation.
- Rationale: staged unit success cannot replace end-to-end security and integration evidence.
- Scope: full unit, PostgreSQL integration, provider fallback, citation/provenance, prompt-injection, leakage, logging, relation promotion, and unexpected-write tests. Out of scope: load/HA/distributed infrastructure.
- Architecture/files: add/extend `tests/unit`, `tests/integration`, and a focused `tests/security` suite; update CI/runbook commands if present.
- Data contracts: test reports include counts/outcomes/config hashes only; secrets and raw content stay out of artifacts.
- LLM vs deterministic: malicious document/user strings remain inside clearly delimited untrusted sections; models cannot call tools or mutate state; deterministic guards validate every output.
- Security/failure modes: instruction-like evidence, provenance tampering, citation swapping, benchmark leakage, relation promotion, raw query logging, SQL injection, provider timeout/retry overflow, and DB writes from read paths.
- Migration/flags: migrate test database to head and verify read-only pipeline transaction behavior; no production migration introduced here.
- Tests: all required unit/integration/security groups from the master instruction, full `pytest`, Ruff, migration lifecycle, and configuration/default-off checks.
- Observability: test evidence and failure codes; redact secrets/content.
- Gate P16: all suites green, no provenance/citation regression, zero security invariant failure, and no unexpected DB write.
- Rollback: rework the owning earlier phase; P16 itself adds tests and should be retained unless erroneous.
- Expected impact: confidence in safety and operability, not a substitute for legal score.

## P17 - Final release dossier

- Objective and weakness: assemble reproducible engineering and legal evidence for an explicit release decision.
- Rationale: release must be based on versioned artifacts and independent legal review, not narrative confidence.
- Scope: finalize architecture, Set A/B/C results, ablation, claim/citation maps, coverage matrices, limitations, tests, gaps, and decision. Out of scope: automatic enablement or legal approval by the coding agent.
- Architecture/files: create/update `docs/architecture/legal-evidence-investigation-architecture.md`, `docs/evals/legal-evidence-investigation-set-a.{md,json}`, `docs/evals/legal-evidence-investigation-set-bc.{md,json}`, `docs/evals/legal-evidence-investigation-ablation.md`, and `docs/review/legal-evidence-investigation-review-dossier.md`; retain this plan.
- Data contracts: architecture/provider/model/profile/corpus versions and hashes; candidate answers in controlled human-review artifact; sanitized authority families, claim/citation maps, coverage, applicability limitations, Set B/C, leakage and test results, remaining gaps, and final decision.
- LLM vs deterministic: no new LLM reasoning; dossier compiles measured evidence. Independent legal reviewer/authorized owner makes legal/release approval.
- Security/failure modes: fabricated/missing measurements, raw private content in JSON, stale hashes, unresolved citations, hidden gaps, or engineering metrics overriding legal score.
- Migration/flags: none; all runtime flags remain off unless a separate explicit approval follows dossier review.
- Tests: artifact schema/hash/link validation, citation resolution sample/full check as specified, privacy scan, reproducibility command verification, final full suite reference.
- Observability: final summarized metrics with provenance to source artifacts.
- Gate P17: dossier complete and internally consistent; engineering requirements pass; legal target and Set C/citation/hallucination requirements are reported exactly. Choose one of `GO_QUALITY_TARGET_MET`, `QUALITY_PASS_PERFORMANCE_REMEDIATION_REQUIRED`, `HOLD_PENDING_LEGAL_REVIEW`, `PASS_WITH_GAPS`, or `NO_GO`.
- Final release rule: engineering phase passes cannot yield `GO_QUALITY_TARGET_MET`. That decision additionally requires the P12 independent full-text result of average `>=8.50/10` and `>=9/10 PASS`, Set C material safety failures `0`, fabricated legal authority `0`, invalid or unresolvable material citations `0`, benchmark leakage `0`, and final human/legal release approval.
- Rollback: correct dossier errors without changing measured source evidence; no runtime rollback is implied.
- Expected impact: produces the auditable release decision and closes the milestone.

## Sequential execution protocol

```text
PLAN ALL PHASES
    |
    v
P1 IMPLEMENT -> TEST -> GATE -> RECORD
    |
    +-- PASS -> AUTO P2
    `-- FAIL -> REWORK P1 -> TEST -> GATE -> RECORD
                    |
                    `-- repeat until PASS or a true blocker exists
    |
    v
... continue the same sequence through P17 ...
    |
    v
FINAL HUMAN / LEGAL RELEASE DECISION
```

1. `MASTER_PLAN_COMPLETE = TRUE` and `IMPLEMENTATION_AUTHORIZED_BY_MASTER_PROMPT = TRUE` authorize automatic sequential implementation from P1 through P17 after this corrective documentation-only task ends.
2. Each phase remains isolated: implement, test, gate, and record only the current phase before beginning the next. Multiple phases are never coded in parallel or gated together.
3. A `PASS` automatically permits and starts the next phase. A failure permits only rework of the same phase until its gate passes or a true blocker exists. Do not ask for routine user approval between phases.
4. Stop only for a destructive or irreversible migration/action; protected repository governance requiring explicit user authority; a missing external credential/dependency that genuinely blocks execution; or final human/legal release approval.
5. Do not edit `.demo-run/state.json`. Only `DEMO_BLOCKER` entries from `contracts/demo-profile.json` may be reported as demo blockers.

## Master plan gate checklist

- [x] Repository, architecture, diagnostics, evaluation, review, and prior plans inspected.
- [x] Current reusable work and conflicting behavior identified.
- [x] P1-P17 objectives, scope, architecture, modules, contracts, responsibilities, controls, failures, migration, flags, tests, observability, gates, rollback, and expected impact defined.
- [x] Dependency graph and architectural decisions recorded.
- [x] Privacy, provenance, provider/source/channel boundaries, default-off behavior, and Reviewed Legal Effects policy preserved.
- [x] Independent legal-quality target distinguished from engineering metrics.
- [x] Sequential phase reporting and rollback protocol defined.
- [x] Automatic PASS-to-next-phase execution and true-blocker stop conditions defined.
- [x] Common measurable quality gates and engineering-versus-legal pass separation defined.

`MASTER_PLAN_COMPLETE = TRUE`

`IMPLEMENTATION_AUTHORIZED_BY_MASTER_PROMPT = TRUE`
