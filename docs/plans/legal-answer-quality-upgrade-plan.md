# Legal Answer Quality Upgrade — Phase-0 Plan

## Scope, supersession, and Gate-0 remediation

This is a documentation-only Phase-0 artifact. It authorizes no source, test,
runtime, configuration, corpus, migration, legal-effect, or production-profile
change.

| Prior stream | State | Treatment |
|---|---|---|
| Phase B continuation | `SUPERSEDED_NOT_MUTATED` | Preserve code, tests, diagnostics, reports, and evaluation evidence. |
| Phase B.2A | `SUPERSEDED_NOT_MUTATED` | Preserve reusable reader/evaluator work. The interrupted NATURAL real run is **not accepted evidence**. |
| Phase B.2B | `SUPERSEDED_NOT_MUTATED` | Preserve all code and evidence; do not continue it. |

Reason: `Superseded by Legal Answer Quality Upgrade master milestone.` No
protected workflow state was changed. Historical retrieval evidence is retained
from `docs/diagnostics/stress-test-fulltext-root-cause.*`,
`docs/diagnostics/phase-b1-retrieval-engine-root-cause.*`, and
`docs/evals/quality-retrieval-repair.*`. It is retrieval diagnostic/configuration
evidence, not an after-state legal-quality score.

**Gate 0 attempt 1 and attempt 2 are BLOCKED.** The final documentation
remediation separates source access from evidence coverage and makes the sealed
holdout non-adaptive. Gate 0 attempt 3 is pending Oracle review; one rereview
remains in the Gate-0 budget.

## Baseline provenance and review protocol

The controlled baseline dependency is the expert full-answer workbook
`docs/Ket_qua_cham_toan_van_Stress_test_Legal_Chatbot_UEB_2026-08-22.xlsx`,
with opaque SHA-256
`88b3ae50f0e135045c170772d7bdd5759b08c132fcb4979a31c21b7a5713fd30`.
It is **EXPERT_REVIEW** evidence, not retrieval diagnostic/configuration
evidence. Its recorded baseline is **5.49 / 10** and **4 / 10 PASS**.

The expert full-answer review stage uses the frozen rubric: A substantive/legal
correctness **4.0**, B authority/source/applicability **2.5**, C completeness
**2.5**, D presentation/traceability/inference discipline **1.0**; `PASS >= 7`.
The MASTER target is separately controlling: Set A average `>= 8.50` and
`>= 9/10 PASS`, with clean citation/provenance, no leakage, and zero Set C
safety/invariant failures. Historical release-gates evidence in
`docs/evals/quality-retrieval/quality-retrieval-plan.contract.json` records an
8/10 threshold and remains unedited; it cannot lower the higher-priority MASTER
threshold.

Reviewer privacy protocol: assign pseudonymous reviewer and case labels; present
only the controlled answer, evidence/citations necessary for scoring, and frozen
rubric; withhold user/channel identifiers, raw request text, prompts, provider
payloads, reconstructed queries, and implementation traces. Store reviewer
identity/conflict declarations separately from scored records. Review materials
must use approved access control, no ordinary logging, and no raw-text export in
machine-readable evaluation outputs.

## Controlled taxonomy and evidence status

The matrix is sanitized: it contains no question text, answers, expected
identities, titles, numbers, URLs, UUIDs, raw/generated query text, or raw
reviewer comments.

Controlled issue labels: `SINGLE_ISSUE_RULE`, `MULTI_ISSUE_RULE`,
`PROCEDURAL_SCOPE`, `ROLE_SCOPE`, `CONDITION_SCOPE`, `SOURCE_SCOPE`,
`APPLICABILITY_SCOPE`, `INSUFFICIENCY_SCOPE`.

Controlled expected-dimension labels: `DIRECT_AUTHORITY`, `SOURCE_SCOPE`,
`PROCEDURAL_COMPLETENESS`, `CONDITION_EXCEPTION`, `MULTI_ISSUE_COVERAGE`,
`APPLICABILITY_QUALIFICATION`, `TRACEABLE_CONCLUSION`,
`SUPPORTED_ABSTENTION`.

Controlled error/status labels: `QUESTION_UNDERSTANDING_FAILURE`,
`QUERY_CONSTRUCTION_FAILURE`, `CANDIDATE_GENERATION_FAILURE`,
`DIRECT_AUTHORITY_SELECTION_FAILURE`, `SUB_INTENT_COVERAGE_FAILURE`,
`FINAL_EVIDENCE_CUTOFF_FAILURE`, `VERSION_OR_APPLICABILITY_UNCERTAINTY`,
`FALSE_INSUFFICIENT_EVIDENCE`, `ANSWER_SYNTHESIS_OMISSION`,
`UNSUPPORTED_LEGAL_INFERENCE`, `CITATION_OR_PROVENANCE_FAILURE`,
`INSUFFICIENCY_RECHECK_REQUIRED`, `NOT_MEASURED`, and `OTHER`.

`EXPERT_REVIEW` can support a full-answer failure classification. Retrieval-only
diagnostic/configuration evidence can support only the observed retrieval or
selection stage; it cannot prove answer generation, false insufficiency, or
legal quality.

## Sanitized Q01–Q10 failure matrix

| case | current score | main legal issues | expected answer dimensions | retrieval failure | evidence-selection failure | answer-generation failure | primary root cause | secondary root cause | evidence provenance | configuration | stage | confidence |
|---|---:|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | 5.2 FAIL | `MULTI_ISSUE_RULE; SOURCE_SCOPE` | `DIRECT_AUTHORITY; MULTI_ISSUE_COVERAGE; TRACEABLE_CONCLUSION` | `QUERY_CONSTRUCTION_FAILURE` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `VERSION_OR_APPLICABILITY_UNCERTAINTY` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; FINAL_SELECTION` | `HIGH` |
| Q02 | 7.0 PASS | `PROCEDURAL_SCOPE; ROLE_SCOPE` | `DIRECT_AUTHORITY; PROCEDURAL_COMPLETENESS; TRACEABLE_CONCLUSION` | `QUERY_CONSTRUCTION_FAILURE` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `QUERY_CONSTRUCTION_FAILURE` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; FINAL_SELECTION` | `HIGH` |
| Q03 | 7.1 PASS | `ROLE_SCOPE; SOURCE_SCOPE` | `DIRECT_AUTHORITY; SOURCE_SCOPE; APPLICABILITY_QUALIFICATION` | `CANDIDATE_GENERATION_FAILURE` | `NOT_MEASURED` | `NOT_MEASURED` | `CANDIDATE_GENERATION_FAILURE` | `OTHER` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; CANDIDATE_SELECTION` | `HIGH` |
| Q04 | 7.1 PASS | `MULTI_ISSUE_RULE; PROCEDURAL_SCOPE` | `DIRECT_AUTHORITY; MULTI_ISSUE_COVERAGE; PROCEDURAL_COMPLETENESS` | `QUERY_CONSTRUCTION_FAILURE` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `DIRECT_AUTHORITY_SELECTION_FAILURE` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; FINAL_SELECTION` | `HIGH` |
| Q05 | 2.5 FAIL | `CONDITION_SCOPE; SOURCE_SCOPE` | `DIRECT_AUTHORITY; CONDITION_EXCEPTION; SOURCE_SCOPE` | `NOT_MEASURED` | `DIRECT_AUTHORITY_SELECTION_FAILURE` | `NOT_MEASURED` | `DIRECT_AUTHORITY_SELECTION_FAILURE` | `OTHER` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC_TOP50; PHASE_B_POOL20` | `FULL_ANSWER_REVIEW; BROAD_CANDIDATE_AVAILABLE; FINAL_SELECTION_UNRESOLVED` | `HIGH` |
| Q06 | 4.5 FAIL | `MULTI_ISSUE_RULE; PROCEDURAL_SCOPE` | `DIRECT_AUTHORITY; MULTI_ISSUE_COVERAGE; PROCEDURAL_COMPLETENESS` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `OTHER` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PHASE_B_POOL20; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; POOL20_4_OF_4_TO_FINAL_1_OF_4; PRODUCTION_EQUIVALENT_FINAL_0_OF_4` | `HIGH` |
| Q07 | 6.0 FAIL | `APPLICABILITY_SCOPE; ROLE_SCOPE` | `DIRECT_AUTHORITY; APPLICABILITY_QUALIFICATION; TRACEABLE_CONCLUSION` | `QUERY_CONSTRUCTION_FAILURE` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `VERSION_OR_APPLICABILITY_UNCERTAINTY` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; FINAL_SELECTION` | `HIGH` |
| Q08 | 1.5 FAIL | `INSUFFICIENCY_SCOPE; SOURCE_SCOPE` | `SUPPORTED_ABSTENTION; DIRECT_AUTHORITY; TRACEABLE_CONCLUSION` | `INSUFFICIENCY_RECHECK_REQUIRED` | `INSUFFICIENCY_RECHECK_REQUIRED` | `NOT_MEASURED` | `OTHER` | `NOT_MEASURED` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; RETRIEVAL_RECHECK_REQUIRED` | `HIGH` |
| Q09 | 8.0 PASS | `SINGLE_ISSUE_RULE; SOURCE_SCOPE` | `DIRECT_AUTHORITY; SOURCE_SCOPE; TRACEABLE_CONCLUSION` | `CANDIDATE_GENERATION_FAILURE` | `DIRECT_AUTHORITY_SELECTION_FAILURE` | `NOT_MEASURED` | `DIRECT_AUTHORITY_SELECTION_FAILURE` | `CANDIDATE_GENERATION_FAILURE` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; CANDIDATE_AND_FINAL_SELECTION` | `HIGH` |
| Q10 | 6.0 FAIL | `MULTI_ISSUE_RULE; APPLICABILITY_SCOPE` | `DIRECT_AUTHORITY; MULTI_ISSUE_COVERAGE; APPLICABILITY_QUALIFICATION` | `QUERY_CONSTRUCTION_FAILURE` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `NOT_MEASURED` | `FINAL_EVIDENCE_CUTOFF_FAILURE` | `VERSION_OR_APPLICABILITY_UNCERTAINTY` | `EXPERT_REVIEW_BASELINE; RETRIEVAL_DIAGNOSTIC` | `WORKBOOK_BASELINE; PRODUCTION_EQUIVALENT_DIAGNOSTIC` | `FULL_ANSWER_REVIEW; FINAL_SELECTION` | `HIGH` |

Matrix interpretation constraints:

- Q05 had broad candidates available. It is an unresolved
  `DIRECT_AUTHORITY_SELECTION_FAILURE` / final-selection problem, **not** a
  `CANDIDATE_GENERATION_FAILURE`.
- Q06’s `4_OF_4_TO_1_OF_4` observation belongs **only** to `PHASE_B_POOL20`.
  The production-equivalent diagnostic final observation was `0_OF_4`; neither
  observation authorizes case-specific logic or a generalized Q06 conclusion.
- Q08 retrieval-only evidence is `INSUFFICIENCY_RECHECK_REQUIRED`. The expert
  workbook may record `FALSE_INSUFFICIENT_EVIDENCE`, but this plan does not
  assert that classification without the controlled expert-review record.
- `FINAL_EVIDENCE_CUTOFF_FAILURE` appears only where the accepted retrieval
  diagnostic explicitly observed the relevant final selection/cutoff stage.
  Otherwise the matrix uses `NOT_MEASURED` or `OTHER`.
- Natural FTS conjunction is supporting `QUERY_CONSTRUCTION_FAILURE` evidence,
  not a standalone FTS-tuning milestone or a blanket conjunction-to-disjunction
  prescription.

## Accepted architecture decisions and invariants

### Pure core, adapters, and runtime

Pure core owns deterministic question analysis, concept-query contracts,
candidate roles, coverage states, evidence-pack contracts, and deterministic
structural claim validation. It imports neither SQLAlchemy, provider/source/
channel SDKs, runtime composition, nor retrieval diagnostics.

Adapters own PostgreSQL title/content/vector execution, port-bound embedding
access, immutable identity/provenance hydration, and citation resolution.
Runtime composition alone binds opt-in controls through `LLMProviderPort`,
`LegalSourcePort`, and `ChannelPort`; it contains no legal heuristic, oracle
data, provider-specific branch, or auto-enable path.

User-derived expanded/repair query text is memory-only and excluded from
ordinary serialization and logs. All quality controls remain default `OFF`.
Reviewed Legal Effects remains `OFF`; no legal effect/currentness conclusion
may be inferred from textual similarity, title, number, date, or relationship.

### Direct-authority allowlist and applicability

Direct-authority assessment may use **only**: immutable document/version/
provenance identity; provenance type/trust; explicitly ingested,
provenance-backed issuer, document-type, and scope fields; and deterministic
issue alignment. It must exclude registry priority/lifecycle, title/number/date
alone, similarity/reranker output, LLM output, unreviewed relationships, legal
effect, and currentness.

Unverified applicability/currentness is a limitation or clarification request,
never a selector conclusion. Reviewed Legal Effects remains `OFF`.

### Planned source binding, source access, and evidence coverage

The analyzer may record `VNU` or `UEB` as a planned source binding. The binding
state is `SOURCE_ACCESS_UNAVAILABLE`: it cannot trigger a live lookup or repair,
imply source availability or authority, alter the read-only source policy, or
replace/purge manual provenance.

`SOURCE_ACCESS_UNAVAILABLE` is not an evidence-coverage result. If eligible
manually ingested evidence exists, it may support a limited answer only with a
manual-provenance disclosure and an applicability limitation. If no eligible
evidence exists, coverage for that unit is `UNAVAILABLE` and synthesis discloses
the gap. Neither branch permits access caused by the binding or an authority
claim caused by planned source membership.

### Claim validator and evaluation placement

The claim validator is deterministic and structural only this milestone. It has
no provider reviewer, no LLM-driven claim adjudication, and no provider call.
Evaluation orchestration is a dedicated diagnostics/evaluation component, not
`RetrievalService` and not runtime composition.

`src/legal_chatbot/chat/planner_service.py` and the legacy provider planner are
explicitly prohibited from modification, import, activation, or aliasing by all
phases of this milestone.

## Frozen ablation contract

| Profile | Frozen meaning | Evidence count | Rerank / repair |
|---|---|---:|---|
| C01 | current production reference | 3 | off / off |
| C02 | document collapse only | **3** | off / off |
| C03 | observable title, content-FTS, and semantic hybrid | **3** | off / off |
| C04 | deterministic analyzer plus protected concept opportunity | **3** | off / off |
| C05 | C04 plus dynamic evidence selection | 3–6, justified only | off / off |
| C06 | C05 plus bounded reranker | 3–6, justified only | on / off |
| C07 | C05 plus exactly one targeted repair | 3–6, justified only | **off / one repair** |
| C08 | C06 plus exactly one targeted repair | 3–6, justified only | **on / one repair** |

C02–C04 always select exactly three final evidence items. C05+ selects three
through six only for material coverage/direct-authority need; no padding is
allowed. C07 and C08 are intentionally distinct. All evaluated profiles remain
runtime-default `OFF`, including after G6.

## Delivery phases, exact future scopes, and Oracle gates

The following are future implementation limits, not authorized Phase-0 edits.
`New` identifies the only permitted new named module/test for that phase. No
recursive path scope applies. Each phase closes only after the stated Oracle
gate; a rejected gate cannot advance.

| Phase | Dependency / owner | Exact future write scope | Verification claim and keep/rollback rule | Mandatory Oracle gate |
|---|---|---|---|---|
| **1 — deterministic analyzer, concept contracts, evaluation-only executor** | G0 / core-retrieval specialist | Existing: `src/legal_chatbot/retrieval/quality_repair/{analyzer.py,models.py,trace.py,__init__.py}`, `src/legal_chatbot/documents/{fts_query.py,quality_candidate_reader.py}`. New: `src/legal_chatbot/diagnostics/evaluation/{__init__.py,orchestrator.py}`. Tests: `tests/unit/{test_quality_repair_contracts.py,test_quality_repair_boundary.py,test_legal_question_analyzer.py,test_legal_answer_quality_orchestrator.py}`. | Bounded deterministic max-four analysis, concept units, `SOURCE_ACCESS_UNAVAILABLE` versus manual-evidence coverage behavior, memory-only traces, and evaluation-only execution; no planner/provider activation. Keep only if unit/boundary proof passes; otherwise revert the full phase delta. | **G1 Contract Oracle** approves taxonomy, source-access/coverage separation, privacy contract, and dedicated evaluator boundary. |
| **2 — hybrid unit candidates, collapse, roles, dynamic selector** | G1 / retrieval-core specialist + PostgreSQL-adapter specialist | Existing: `src/legal_chatbot/retrieval/quality_repair/{models.py,ranking.py,strategy.py}`, `src/legal_chatbot/documents/{hybrid_retrieval_repository.py,retrieval_repository.py,semantic_embedding_repository.py,quality_candidate_reader.py}`. New: `src/legal_chatbot/retrieval/quality_repair/{candidate_roles.py,evidence_budget.py}`. Tests: `tests/unit/{test_quality_candidate_reader.py,test_quality_repair_ranking.py,test_candidate_roles.py,test_evidence_budget.py}`; `tests/integration/{test_quality_candidate_reader.py,test_legal_answer_quality_hybrid_postgres.py}`. | Observable independent title/content/vector contributions; collapse only on complete document/version/provenance equality; retained supporting chunks; allowlisted direct roles; C02–C04=3 and C05+=3–6 without padding. Keep only if unit/PG read-only and no-padding proof passes; else revert phase delta. | **G2 Candidate Oracle** approves observability, collapse equality, authority allowlist application, and selector evidence. |
| **3 — completeness matrix and one targeted repair** | G2 / evidence-core specialist + retrieval-adapter specialist | Existing: `src/legal_chatbot/retrieval/quality_repair/{models.py,strategy.py}`, `src/legal_chatbot/documents/{quality_candidate_reader.py,hybrid_retrieval_repository.py}`. New: `src/legal_chatbot/retrieval/quality_repair/{coverage.py,repair.py}`. Tests: `tests/unit/{test_evidence_coverage.py,test_targeted_repair.py}`; `tests/integration/test_legal_answer_quality_repair_postgres.py`. | Per-unit supported/partial/unsupported/ambiguous/unavailable matrix; exactly one memory-only repair targets a recorded gap, cannot loop or use a reranker/oracle; unresolved parts become limitations. Keep only if bounds, no false completion, unavailable-source, and read-only proof pass; else revert phase delta. | **G3 Completeness Oracle** approves status semantics, trigger, disclosure behavior, and C07/C08 separation. |
| **4 — pure structured evidence pack and claim-validator contracts** | G3 / chat-core specialist + citation/provenance specialist | Existing: `src/legal_chatbot/documents/{grounding_evidence.py,citation_resolver.py,canonical_anchor_resolver.py}`, `src/legal_chatbot/retrieval/quality_repair/models.py`. New: `src/legal_chatbot/retrieval/quality_repair/{evidence_pack.py,claim_validation.py}`. Tests: `tests/unit/{test_structured_evidence_pack.py,test_structural_claim_validation.py,test_evidence_pack_provenance.py}`. | Pure typed pack and deterministic structural claim/citation outcomes only; no prompt serialization, parser, provider call, or runtime composition in G4. Keep only if citation/provenance, import-boundary, and unsupported-claim handling proof pass; else revert phase delta. | **G4 Pack/Validator Oracle** approves pure contracts, claim classes, limitation behavior, and absence of provider review. |
| **5 — bounded provider boundary, default-off composition, evaluation tooling** | G4 / runtime-integration specialist + evaluation specialist | Existing: `src/legal_chatbot/chat/{models.py,prompt.py,parser.py,service.py,config.py}`, `src/legal_chatbot/{runtime/m08.py,main.py,retrieval/config.py,diagnostics/__init__.py}`, `src/legal_chatbot/diagnostics/evaluation/{__init__.py,orchestrator.py}`. New: `src/legal_chatbot/diagnostics/evaluation/{ablation.py,leakage.py,run_manifest.py}`. Tests: `tests/unit/{test_chat_prompt.py,test_chat_parser.py,test_grounded_chat_service.py,test_legal_answer_quality_ablation.py,test_legal_answer_quality_leakage.py}`; `tests/integration/{test_m06_chat_fake_provider.py,test_m06_grounded_chat_shine_live.py,test_legal_answer_quality_end_to_end.py}`. | Bounded prompt serialization, provider-input budget, output/parser schema, citation rendering, default-off composition, and end-to-end six-evidence compatibility through `LLMProviderPort`. Keep only if import/privacy/citation/leakage/default-off and six-evidence compatibility proofs pass; else revert phase delta. **G5 precedes every live C05–C08 answer ablation.** | **G5 Runtime/Evaluation Oracle** approves provider boundary, frozen profile mapping, run-manifest protocol, and no-auto-enable proof. |
| **6 — evaluation, remediation, expert review, final artifacts** | G5 / evaluation specialist + legal-review owner | Existing: `src/legal_chatbot/diagnostics/evaluation/{orchestrator.py,ablation.py,leakage.py,run_manifest.py}`. New: none without a separate Oracle-approved iteration addendum naming files. Evaluation outputs only: `docs/evals/{legal-answer-quality-upgrade.md,legal-answer-quality-upgrade.json,legal-answer-quality-upgrade.csv,legal-answer-quality-ablation.md,legal-answer-quality-case-review.md}`. Tests: `tests/unit/test_legal_answer_quality_orchestrator.py`, `tests/integration/test_legal_answer_quality_end_to_end.py`. | Execute Set A/B/C, C01–C08 ablation, leakage scan, and controlled full-answer expert review. At most three generalized iterations; all flags off. Keep/rollback uses the policy below. | **G6 Release Oracle** reviews measured evidence and may consider, but does not imply, a separate production-enable authorization. |

## Evidence path, credibility, and evaluation gates

1. **Unit and PostgreSQL integration:** establish contract, identity/provenance
   collapse, role/coverage, repair-bound, read-only, query-count, and warmed
   latency evidence. Technical metrics are supporting evidence only.
2. **Privacy/import/citation/provenance:** prove excluded data does not serialize
   or log; pure-core import boundaries hold; each citation resolves through an
   immutable document/version/provenance identity.
3. **Leakage scanner:** fail on benchmark case IDs, literals, expected
   identities, aliases, source forcing, or case-specific thresholds in
   production paths.
4. **Pre-registration and sealed holdout:** before adaptive evaluation begins,
   the evaluation owner pre-registers and seals a legal-quality holdout that is
   inaccessible to implementers throughout all three-or-fewer iterations. Set A
   remains the MASTER primary target. After the final configuration is frozen,
   run the holdout exactly once. It is mandatory to claim generalization or
   rollout readiness, not a substitute for Set A. A holdout failure permits no
   such claim and must not trigger tuning, an additional holdout run, or any
   rollback/keep decision against holdout results.
5. **Run manifest:** before any scored live run, freeze the SHINE model/version,
   prompt/config identifiers, sampling settings, retry policy, timing protocol,
   corpus snapshot/hash, and run count in the controlled evaluation manifest.
   Missing frozen fields block scoring; no values are invented in this plan.
6. **Set B/C and ablation:** evaluate frozen paraphrases and controls, require
   zero Set C safety/invariant failures, and compare C01–C08 component by
   component. Live C05–C08 answer ablation cannot begin before G5.
7. **Expert full-answer review:** qualified independent reviewers act under
   pseudonymous, blinded case/config presentation. They declare conflicts;
   conflicts remove a reviewer from affected material. Disagreements follow a
   controlled independent adjudication path. Aggregate per-case and aggregate
   results using the frozen rubric and documented aggregation rule; retain only
   sanitized outputs. The expert workbook is the source for legal-quality
   scores, never retrieval diagnostics.

Credible final legal-quality scoring requires both a controlled SHINE live run
through `LLMProviderPort` and the controlled expert-review workbook process.
Before those dependencies are complete, report `NOT_MEASURED`; do not fabricate
holdout, after-score, PASS, ablation, or release results.

## Generalized remediation, no-auto-enable, and rollback

Phase 6 allows at most three iterations. Before each, record a controlled error
class, generalized hypothesis, affected component, exact approved files, and
pre-registered Set A/B/C and ablation comparison. A remediation must not use a
case, expected identity, title, number, source forcing, or benchmark wording.

Every iteration starts at the latest Oracle-accepted snapshot and all flags stay
`OFF`. Run unit/PG, privacy/import, citation/provenance, leakage, pre-registered
Set A/B/C, and ablation checks. Iteration keep decisions use those
pre-registered Set A/B/C and ablation results **only**: retain only with
Oracle-accepted predicted generalized improvement, no material Set B regression,
zero Set C safety/invariant failures, clean provenance/citations, no leakage,
and preserved default-off behavior. Otherwise roll back the entire iteration,
retain its report as negative evidence, and do not auto-enable any profile.

Only after the final configuration is frozen, run the sealed holdout once. A
holdout failure bars a generalization or rollout-readiness claim; it never
triggers a tuning iteration, re-run, keep/rollback decision, or production
enablement. A keep result never enables production; only a separately approved
decision after G6 can do that.

## Gate status and remaining blocker

Gate order is `G0 → P1/G1 → P2/G2 → P3/G3 → P4/G4 → P5/G5 → P6/G6`.
Each gate has one initial Oracle review and at most two rereviews. Gate 0 attempts
1 and 2 are blocked; attempt 3 is pending, with one rereview remaining. The
remaining blocker is Oracle acceptance of this final remediated Gate-0 plan;
after G5, credible scoring additionally depends on the frozen final configuration,
one sealed-holdout run, frozen SHINE run manifest/live run, and controlled expert
review process.

## Required final artifacts

After measured execution only:

- `docs/evals/legal-answer-quality-upgrade.md`
- `docs/evals/legal-answer-quality-upgrade.json`
- `docs/evals/legal-answer-quality-upgrade.csv`
- `docs/evals/legal-answer-quality-ablation.md`
- `docs/evals/legal-answer-quality-case-review.md`
- MASTER-format final report with measured values and final Oracle decision.
