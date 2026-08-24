# MASTER EXECUTION OVERRIDE
# LEGAL ANSWER QUALITY UPGRADE
## Stop Previous Work → Replan → Implement End-to-End Quality Improvement

> **Execution priority: HIGHEST**
>
> This file supersedes all previously pending retrieval-quality, diagnostic,
> remediation, tuning, and milestone instructions unless they are explicitly
> referenced here as evidence or reusable implementation work.

---

# 0. EXECUTION OVERRIDE — STOP PREVIOUS TASKS FIRST

Before doing any new implementation work, perform a safe execution-state review.

## 0.1 Stop / discontinue pending previous work

STOP and DO NOT CONTINUE any unfinished or planned work whose primary purpose is:

- Phase B continuation;
- Phase B.2A;
- Phase B.2B;
- isolated FTS tuning;
- isolated semantic-latency tuning;
- HNSW optimization as a standalone milestone;
- candidate-pool tuning as a standalone milestone;
- reranker tuning from prior plans;
- automatic continuation of Phase C–H from the old milestone;
- any previous remediation loop that optimizes technical metrics without directly measuring final legal-answer quality;
- any previously queued task that conflicts with this prompt.

Do NOT delete useful code, tests, diagnostics, reports, migrations, or evidence already produced.

Do NOT manually edit protected workflow/gate state files.

If the repository has an approved gate/task-state mechanism:

1. inspect current state;
2. safely close, cancel, defer, or mark superseded any old unfinished task using the repository's supported workflow;
3. record the reason:

   "Superseded by Legal Answer Quality Upgrade master milestone."

If a previous task cannot be safely cancelled because of repository governance,
do not force-edit its state. Record it as:

    SUPERSEDED_NOT_MUTATED

and continue this new milestone through the valid repository mechanism.

## 0.2 Preserve previous findings as evidence

Previous reports are NOT discarded.

Treat them as diagnostic evidence, especially:

- docs/diagnostics/stress-test-fulltext-root-cause.md
- docs/evals/quality-retrieval-repair.md
- docs/evals/quality-retrieval-repair.json
- docs/diagnostics/phase-b1-retrieval-engine-root-cause.md
- docs/diagnostics/phase-b1-retrieval-engine-root-cause.json

Do not repeat solved diagnostics unless current runtime evidence contradicts them.

## 0.3 New primary objective

From this point onward, the project is QUALITY-DRIVEN.

Every implementation decision must answer:

> Does this make the chatbot understand the legal question better, retrieve
> the right legal authority, cover the material legal issues more completely,
> and produce a more trustworthy final answer?

Infrastructure, latency, retrieval metrics, query plans, indexing and tests are
supporting constraints.

They are NOT the final success criterion.

---

# 1. PRIMARY BUSINESS GOAL

Current full-text legal-answer baseline:

- Average score: **5.49 / 10**
- PASS: **4 / 10 questions**

Target:

- Average score: **>= 8.50 / 10**
- PASS: **>= 9 / 10 questions**
- Preserve the frozen legal-quality rubric and PASS threshold.
- No benchmark-specific production hard-code.
- No material regression on paraphrases or negative/control questions.

The milestone succeeds only if the **FINAL LEGAL ANSWERS** improve.

A technically cleaner retrieval engine that still produces weak legal answers
does NOT constitute success.

---

# 2. ESTABLISHED FINDINGS — DO NOT REDIAGNOSE FROM ZERO

Read the current repository, current tests, current contracts and the reports listed above before making changes.

The live code is authoritative when it differs from old plans.

Treat the following as established unless new runtime evidence disproves them:

1. Natural semantic broad retrieval previously reached approximately **24/29** expected identities.
2. Document-level collapse is useful: duplicate chunks from the same document consumed early candidate budget.
3. CONTENT_FTS natural-query failure is primarily a **query-construction recall limitation** caused by overly restrictive natural conjunction.
4. TITLE_FTS has the same query-construction problem in most measured cases, while some titles genuinely cannot match the natural question by title terms alone.
5. Do NOT solve FTS by blindly changing every `AND` into `OR`.
6. Q6 proved a major downstream evidence-selection failure: **4/4 expected documents entered the candidate pool but only 1/4 survived fixed final top-3**.
7. Fixed `final_top_k=3` is insufficient for some multi-part legal questions.
8. Semantic retrieval remains the strongest effective retrieval lane today.
9. Cold-start and exact diagnostic execution distorted earlier latency interpretation.
10. Ranking/collapse/fusion computation themselves were not the dominant measured cost.
11. HNSW capability exists; a diagnostic exact sequential scan is not, by itself, evidence of a PostgreSQL planner failure.
12. Reviewed Legal Effects remains **OFF**.

Do not reopen these questions as standalone investigations unless they block a specific answer-quality improvement.

---

# 3. NON-NEGOTIABLE QUALITY MODEL

A trustworthy Legal Chatbot must solve five distinct problems:

1. Understand what the user is actually asking.
2. Find the legal material that directly governs the material issues.
3. Determine whether enough evidence exists for every material part.
4. Distinguish source facts from legal inference.
5. Generate a complete answer whose important claims can be traced to evidence.

Target architecture:

    USER QUESTION
          ↓
    Conversation / Request Context
          ↓
    Question Understanding
          ↓
    Legal Issue / Sub-intent Analysis
          ↓
    Retrieval Query Construction
          ↓
    Title + Content FTS + Semantic Retrieval
          ↓
    Document-level Collapse
          ↓
    Candidate Fusion / Coverage
          ↓
    Authority / Applicability Assessment
          ↓
    Evidence Completeness Check
          ↓
    One Bounded Repair Retrieval if required
          ↓
    Structured Evidence Pack
          ↓
    Legal Answer Synthesis
          ↓
    Claim ↔ Evidence Validation
          ↓
    Final Answer

Do NOT reduce the design back to:

    raw question → embedding → top3 → LLM

---

# 4. PHASE 0 — ANALYZE CURRENT LEGAL-QUALITY FAILURE MODES

Before implementation, inspect the current pipeline and create:

    docs/plans/legal-answer-quality-upgrade-plan.md

Then CONTINUE IMPLEMENTATION AUTOMATICALLY.

Do not stop and ask the user for routine approval between safe, reversible steps.

The plan must classify observed failures into:

- QUESTION_UNDERSTANDING_FAILURE
- QUERY_CONSTRUCTION_FAILURE
- CANDIDATE_GENERATION_FAILURE
- DIRECT_AUTHORITY_SELECTION_FAILURE
- SUB_INTENT_COVERAGE_FAILURE
- FINAL_EVIDENCE_CUTOFF_FAILURE
- VERSION_OR_APPLICABILITY_UNCERTAINTY
- FALSE_INSUFFICIENT_EVIDENCE
- ANSWER_SYNTHESIS_OMISSION
- UNSUPPORTED_LEGAL_INFERENCE
- CITATION_OR_PROVENANCE_FAILURE
- OTHER

For Q01–Q10 create a failure matrix containing:

- case
- current score
- main legal issues
- expected answer dimensions
- retrieval failure
- evidence-selection failure
- answer-generation failure
- primary root cause
- secondary root cause

Expected document identities are EVALUATION ORACLE ONLY.

Never insert benchmark expected IDs/titles/numbers into production logic.

---

# 5. PHASE 1 — LEGAL QUESTION UNDERSTANDING

Implement or improve a bounded deterministic Legal Question Analyzer.

`QUALITY_QUERY_PLANNER` is ONLY an alias for this deterministic analyzer.

It MUST NOT activate:

- legacy planner;
- LLM planner;
- provider-driven query planning;
- hidden benchmark-specific rules.

Analyzer should support:

- intent;
- legal subject / actor;
- action or event;
- organization / scope;
- explicit relevant time;
- legal topics;
- complexity;
- ambiguity;
- sub_intents;
- per-sub-intent source binding.

Maximum:

    4 sub-intents

Do not over-decompose simple questions.

Possible legal intents include:

- eligibility / conditions;
- procedure;
- authority;
- prohibition;
- obligation;
- rights;
- legal consequence;
- evaluation criteria;
- document management;
- validity / applicability;
- multi-stage process.

Example concept:

A question about buying an asset, putting it into management, and inventorying
it should be recognized as potentially containing distinct issues such as:

- purchasing authority;
- purchasing procedure;
- asset management;
- inventory.

The analyzer must generalize.

No question-specific code.

## 5.1 Per-unit source binding

Each sub-intent can independently carry:

- VBQPPL
- VNU
- UEB
- UNKNOWN
- AMBIGUOUS

Do NOT force AMBIGUOUS into a source just to improve recall.

A legal question may legitimately require multiple source tiers.

## 5.2 Privacy / trace contract

Every user-derived or identity-bearing field must remain excluded from ordinary
serialization/logging according to the frozen contract.

Expanded query and repair query text are:

    MEMORY ONLY

Never persist or log reconstructed user query text.

---

# 6. PHASE 2 — LEGAL RETRIEVAL QUERY CONSTRUCTION

Current long natural-language conjunction has been proven to destroy recall.

Replace it with a bounded concept-aware query construction strategy.

Do NOT use, as a general rule:

    token1 AND token2 AND token3 ... AND token25

Do NOT replace it with uncontrolled:

    token1 OR token2 OR token3 ... OR token25

Instead construct retrieval units from:

- core legal concepts;
- extracted entities;
- legal actions;
- legal topics;
- important noun phrases;
- normalized organization names;
- explicit document numbers supplied by the user;
- deterministic aliases/synonyms when safe;
- individual sub-intents.

Conceptually:

    QUESTION
       ↓
    SUB-INTENTS
       ↓
    CORE CONCEPT GROUPS
       ↓
    BOUNDED LEXICAL QUERIES

Example concept pattern:

    ("quản lý tài sản")
 OR ("kiểm kê tài sản")
 OR ("mua sắm tài sản")

rather than requiring all natural-question words to coexist.

The exact query primitive must fit the existing PostgreSQL implementation.

Prioritize retrieval recall first, then ranking/selection.

---

# 7. PHASE 3 — TRUE HYBRID CANDIDATE RETRIEVAL

Use independent observable lanes:

1. TITLE / METADATA
2. CONTENT FTS
3. SEMANTIC VECTOR

For each candidate retain, where supported:

- document identity;
- document version identity;
- provenance identity;
- title contribution;
- lexical contribution;
- semantic contribution;
- rank per lane;
- fused score;
- sub-intent coverage;
- source tier;
- directness / authority signals.

Do not expose user-derived query text in logs.

## 7.1 Document-level collapse

Collapse duplicate chunks BEFORE document candidate budget is consumed.

Collapse ONLY when required full identity/provenance equality is satisfied.

Do NOT merge merely because:

- normalized document number matches;
- titles are similar;
- source names are similar.

Preserve the best supporting chunks for evidence and citations.

---

# 8. PHASE 4 — CANDIDATE COVERAGE, NOT ONLY GLOBAL SIMILARITY

A multi-part legal question must not allow one topic to occupy the entire candidate budget.

Candidate selection should consider:

- relevance;
- sub-intent coverage;
- source relevance;
- direct legal authority;
- document diversity.

Do NOT require every answer to contain all of:

    VBQPPL + VNU + UEB

Only preserve a source tier when it is actually relevant.

Do not force ambiguous source routing.

Distinguish conceptually:

- DIRECT_AUTHORITY
- IMPLEMENTING_OR_INTERNAL_RULE
- SUPPLEMENTARY_AUTHORITY
- BACKGROUND
- IRRELEVANT

Repository-specific enum names may differ.

A document with high semantic similarity but weak governing relevance should
not automatically outrank the document that directly regulates the legal issue.

---

# 9. PHASE 5 — DYNAMIC EVIDENCE BUDGET

Respect frozen strategy-profile contracts.

For C02–C04:

    final evidence = 3

For C05+ only:

    MIN evidence = 3
    MAX evidence = 6

Dynamic evidence does NOT mean padding.

Do not fill six slots just because six are available.

Evidence budget should reflect actual legal need:

- number of material sub-intents;
- number of direct authorities;
- relevant source tiers;
- unresolved coverage gaps;
- implementing/supporting rules.

A simple one-issue question may need only 3.

A four-part legal question with separate controlling evidence must be able to
retain more than 3 when justified.

The previously observed Q6 final-cutoff failure must become solvable through a GENERALIZED mechanism.

Do not hard-code Q6.

Reranker confidence MUST NOT be used before the existing approved Gate G permits it.

---

# 10. PHASE 6 — EVIDENCE COMPLETENESS GATE

Before answer generation, build an internal Evidence Coverage Matrix.

For every material sub-intent classify:

- SUPPORTED
- PARTIALLY_SUPPORTED
- UNSUPPORTED
- AMBIGUOUS

Also assess:

- direct authority present?
- source scope appropriate?
- evidence sufficiently specific?
- legal-status/version uncertainty?
- conflicting evidence?

Example:

    Sub-intent 1 → SUPPORTED
    Sub-intent 2 → SUPPORTED
    Sub-intent 3 → UNSUPPORTED
    Sub-intent 4 → SUPPORTED

This is NOT a complete evidence pack.

The generator must not silently answer all four as if all were supported.

---

# 11. PHASE 7 — ONE BOUNDED REPAIR RETRIEVAL

If a material coverage gap remains, permit exactly ONE targeted repair retrieval.

Repair retrieval targets:

    MISSING LEGAL CONCEPT / MISSING SUB-INTENT

It does not simply replay the entire original query.

Rules:

- one repair pass maximum;
- no infinite loop;
- no provider retry loop;
- no expected-document oracle;
- no benchmark lookup;
- no hidden corpus expansion during this milestone unless already authorized elsewhere by repository policy.

Repair query text is memory-only.

After repair:

- if coverage becomes sufficient → answer;
- if still incomplete → answer supported parts and disclose the unresolved part;
- never hallucinate missing law.

---

# 12. PHASE 8 — LEGAL AUTHORITY / APPLICABILITY DISCIPLINE

The chatbot must distinguish:

- relevant evidence;
- direct governing authority;
- supplementary evidence;
- internal implementation rule;
- unverified applicability/current effect.

Reviewed Legal Effects remains:

    OFF

unless a separate approved gate explicitly authorizes otherwise.

Do NOT infer:

- AMENDS
- REPLACES
- REPEALS
- SUPERSEDES
- temporal legal effect

from textual similarity, document numbers, dates alone, or titles alone.

Existing legal-status metadata may be surfaced only within its real provenance and confidence.

If current applicability cannot be safely established, state that limitation.

---

# 13. PHASE 9 — STRUCTURED LEGAL ANSWER SYNTHESIS

The answer generator must receive a STRUCTURED EVIDENCE PACK rather than only a flat list of chunks.

Evidence pack should contain:

## QUESTION ANALYSIS
## SUB-INTENTS
## SELECTED LEGAL AUTHORITIES
## COVERAGE MATRIX
## KNOWN LIMITATIONS

For each authority, where available:

- title;
- normalized number;
- authority/source;
- version identity;
- available legal-status metadata;
- supporting chunks;
- supported sub-intents;
- direct/supporting role;
- provenance/citation identifiers.

The generator should conceptually produce:

1. KẾT LUẬN NGẮN
2. CĂN CỨ PHÁP LÝ CHÍNH
3. PHÂN TÍCH THEO TỪNG VẤN ĐỀ
4. ÁP DỤNG / Ý NGHĨA THỰC TIỄN
5. ĐIỀU KIỆN, NGOẠI LỆ HOẶC ĐIỂM CHƯA ĐỦ CĂN CỨ
6. TRÍCH DẪN / NGUỒN

Do not mechanically emit all headings for very simple answers.

## 13.1 Legal reasoning discipline

Every important statement should conceptually be one of:

- SOURCE_FACT
- SUPPORTED_INTERPRETATION
- LIMITATION
- NEXT_CHECK

Do not blur source fact with unsupported case-specific conclusion.

---

# 14. PHASE 10 — CLAIM ↔ EVIDENCE VALIDATION

Before final release, validate material legal claims.

For each important claim:

- identify supporting evidence;
- identify citation;
- verify the cited evidence supports the claim;
- detect unsupported conclusions;
- detect over-broad inference;
- detect missing answer dimensions.

Possible internal outputs:

- SUPPORTED
- SUPPORTED_WITH_QUALIFICATION
- UNSUPPORTED
- EVIDENCE_CONFLICT
- INSUFFICIENT_CONTEXT

Material UNSUPPORTED claims must be removed, rewritten, or explicitly qualified.

The validator may not invent new legal facts.

---

# 15. WHAT "SMARTER" MEANS

A smarter legal answer:

- recognizes the actual legal issue;
- separates complex issues correctly;
- searches using legal concepts rather than raw sentence tokens;
- selects direct authority over merely similar text;
- gathers enough evidence for material issues;
- recognizes uncertainty;
- avoids unsupported legal conclusions;
- explains the relationship between rules and the user's question;
- cites evidence precisely.

Do NOT measure intelligence by answer length, number of documents, number of retrieval lanes, or number of AI calls.

---

# 16. AUTOMATED GENERALIZED IMPROVEMENT LOOP

The Coding Agent is authorized to perform reversible in-repository work without routine intermediate user confirmation.

Maximum:

    3 GENERALIZED QUALITY REMEDIATION ITERATIONS

Each remediation iteration must:

1. measure;
2. identify an ERROR CLASS;
3. state a generalized hypothesis;
4. implement a generalized fix;
5. run Set A;
6. run Set B;
7. run Set C;
8. run ablation;
9. keep or rollback based on evidence.

Forbidden:

    Q05 failed
    → add Q05-specific keyword
    → Q05 passes
    → keep

Required style:

    a class of multi-intent questions loses domain coverage
    → implement generalized sub-intent preservation
    → test originals, paraphrases and controls

Do not tune indefinitely.

---

# 17. BENCHMARK-LEAKAGE PROTECTION

Production code MUST NOT contain:

- Q01–Q10 literal question strings;
- expected document numbers;
- expected document titles;
- benchmark-specific aliases;
- benchmark-specific source forcing;
- case-ID conditionals;
- special thresholds for benchmark questions.

Expected identities are evaluation-oracle data only.

Add or preserve automated leakage checks.

If production benchmark-specific behavior is detected:

    FAIL THE MILESTONE

---

# 18. EVALUATION SETS

## SET A
Current 10 legal stress-test questions.

## SET B
At least 30 paraphrases, minimum 3 per original question.

Vary wording, sentence structure, formal vs conversational Vietnamese,
abbreviations, implicit organization references, and direct vs indirect phrasing.

## SET C
At least 20 negative/control questions, including outside-corpus, ambiguous,
insufficient-fact, irrelevant-topic, near-match but legally different, and
correct-abstention questions.

Do not optimize only against Set A.

---

# 19. PRIMARY LEGAL QUALITY RUBRIC

Use the frozen full-text legal review rubric.

Total: 10 points.

A. LEGAL FACTUAL / SUBSTANTIVE CORRECTNESS — 4.0
B. CORRECT AUTHORITY / SOURCE / APPLICABILITY — 2.5
C. COMPLETENESS OF LEGAL ANSWER — 2.5
D. PRESENTATION / TRACEABILITY / INFERENCE DISCIPLINE — 1.0

Preserve the existing PASS threshold.

Report both automated structural metrics and full-text legal-quality score.

`ANSWER_GROUNDED` alone is NOT sufficient.

---

# 20. PRIMARY RELEASE GATE

PRIMARY QUALITY TARGET:

    Average legal quality >= 8.50 / 10
    PASS >= 9 / 10 Set A
    Benchmark leakage = NONE
    Set C safety/invariant failures = 0
    Citation/provenance invariants = clean

This is the PRIMARY definition of success.

No technical metric may replace it.

---

# 21. SECONDARY DIAGNOSTIC METRICS

Measure and report:

- question-analysis accuracy;
- sub-intent coverage;
- source-binding accuracy;
- title hit rate;
- lexical hit rate;
- semantic hit rate;
- fused candidate recall;
- direct-authority recall;
- document-level diversity;
- final evidence coverage;
- repair activation rate;
- repair success rate;
- false insufficient-evidence rate;
- unsupported-claim rate;
- citation validity;
- wrong-document rate;
- paraphrase consistency;
- negative/control behavior;
- warmed retrieval latency p50/p95;
- answer latency if available;
- DB query count.

Do NOT prioritize micro-optimizing latency while final answer quality remains weak.

If answer quality target is met but performance still needs work, report:

    QUALITY_TARGET_MET_PERFORMANCE_REMEDIATION_REQUIRED

---

# 22. ABLATION

Use current named strategy profiles.

Respect frozen contracts:

- all quality flags default OFF;
- C02–C04 final evidence fixed at 3;
- only C05+ dynamic 3–6;
- no evidence padding;
- C07 and C08 must represent meaningfully different strategies;
- QUALITY_QUERY_PLANNER is deterministic analyzer alias only.

Measure at least:

1. current production reference;
2. document collapse;
3. question understanding;
4. improved FTS query construction;
5. hybrid fusion;
6. sub-intent candidate coverage;
7. dynamic evidence;
8. evidence completeness;
9. one repair retrieval;
10. structured answer synthesis;
11. claim/evidence validator;
12. full quality configuration.

Do not claim improvement without ablation evidence.

---

# 23. TEST / SAFETY REQUIREMENTS

Preserve or improve:

- unit tests;
- PostgreSQL integrations;
- citation invariants;
- provenance integrity;
- immutable document/version identities;
- reviewed-effect registry safety;
- security controls;
- provider-output protections.

Reviewed Legal Effects:

    OFF

All new quality features:

    DEFAULT OFF

until the final release gate is explicitly satisfied.

No destructive migration.
No silent corpus rewrite.
No hidden legal-effect import.
No automatic amendment/replacement/repeal inference.

---

# 24. REQUIRED ARTIFACTS

Create/update:

    docs/plans/legal-answer-quality-upgrade-plan.md
    docs/evals/legal-answer-quality-upgrade.md
    docs/evals/legal-answer-quality-upgrade.json
    docs/evals/legal-answer-quality-upgrade.csv
    docs/evals/legal-answer-quality-ablation.md
    docs/evals/legal-answer-quality-case-review.md

Machine-readable result should include per case:

- case_id
- score_before
- score_after
- pass_before
- pass_after
- analyzed_intents
- sub_intent_count
- source_bindings
- broad_candidate_count
- direct_authority_count
- evidence_count
- evidence_coverage
- repair_used
- repair_result
- unsupported_claim_count
- citation_count
- answer_state
- primary_remaining_error_class

Do not serialize frozen excluded user-derived/identity-bearing fields.

---

# 25. REQUIRED FINAL REPORT

Print at completion:

============================================================
LEGAL ANSWER QUALITY UPGRADE — FINAL
============================================================

Previous pending work:
STOPPED / SUPERSEDED / SUPERSEDED_NOT_MUTATED

Baseline:
Average: 5.49 / 10
PASS: 4 / 10

After:
Average: X / 10
PASS: X / 10

Target:
Average >= 8.50 / 10
PASS >= 9 / 10

Target status:
MET / NOT_MET

Per-question:
Q01 before → after
Q02 before → after
Q03 before → after
Q04 before → after
Q05 before → after
Q06 before → after
Q07 before → after
Q08 before → after
Q09 before → after
Q10 before → after

Retrieval quality:
Title contribution:
Content FTS contribution:
Semantic contribution:
Hybrid contribution:
Direct-authority recall:
Final evidence coverage:

Understanding:
Analyzer success:
Complex-question decomposition:
Sub-intent coverage:
Ambiguous-source handling:

Evidence:
False insufficient:
Repair retrieval success:
Unsupported material claims:
Citation invariant failures:

Generalization:
Set B paraphrase result:
Set C control result:
Benchmark leakage:
NONE / DETECTED

Ablation contribution:
Document collapse:
Question understanding:
FTS construction:
Hybrid fusion:
Coverage:
Dynamic evidence:
Completeness gate:
Repair:
Answer synthesis:
Claim validator:

Performance:
Warmed retrieval p50:
Warmed retrieval p95:
Cold-start note:
DB query count:

Safety:
Reviewed Legal Effects: OFF
Quality flags default: OFF
DB unexpected writes: 0

Remaining weaknesses:
1.
2.
3.

FINAL DECISION:

GO_QUALITY_TARGET_MET

or

QUALITY_TARGET_MET_PERFORMANCE_REMEDIATION_REQUIRED

or

PASS_WITH_GAPS

or

NO_GO_QUALITY_TARGET_NOT_MET

============================================================

---

# 26. STOP CONDITIONS

## GO_QUALITY_TARGET_MET

Only when:

- average >= 8.50;
- at least 9/10 PASS;
- Set C zero safety/invariant failures;
- citations/provenance clean;
- no benchmark hard-code.

## QUALITY_TARGET_MET_PERFORMANCE_REMEDIATION_REQUIRED

Use when legal-quality target is met but warmed production-equivalent
performance still requires optimization.

## PASS_WITH_GAPS

Use when substantial generalized quality improvement is proven and safety is
preserved, but one or more primary quality targets remain below threshold.

## NO_GO_QUALITY_TARGET_NOT_MET

Use when quality improvement is marginal, regression occurs, benchmark leakage
exists, or generalized quality gains cannot be demonstrated.

Do NOT call the milestone successful merely because tests pass, recall rises,
latency improves, more documents are retrieved, or an answer is grounded.

Success means:

> BETTER LEGAL ANSWERS.

---

# 27. EXECUTION AUTHORITY

Proceed automatically through:

    inspect current task/gate state
          ↓
    safely stop/supersede previous unfinished work
          ↓
    read current code + existing reports
          ↓
    create failure matrix
          ↓
    create implementation plan
          ↓
    implement generalized quality improvements
          ↓
    test
          ↓
    Set A / B / C evaluation
          ↓
    bounded remediation, maximum 3 iterations
          ↓
    ablation
          ↓
    final full-text legal-quality evaluation
          ↓
    final report

Do NOT ask for routine confirmation between these steps.

Do NOT automatically enable the new production quality configuration.

Keep quality functionality behind strategy flags until the final Gate is known.

If >=8.50 average and >=9/10 PASS cannot be reached after the bounded iterations,
STOP with the best measured generalized configuration and explain the remaining
failure classes.

Do NOT continue endless tuning.

---

# 28. START NOW

Start by:

1. reading repository task/gate state;
2. safely stopping or superseding old pending work;
3. confirming previous diagnostics are retained as evidence;
4. reading current implementation;
5. producing the Q01–Q10 legal-quality failure matrix;
6. creating `docs/plans/legal-answer-quality-upgrade-plan.md`;
7. continuing automatically into implementation.

The controlling priority from this point onward is:

    FINAL LEGAL ANSWER QUALITY
          >
    isolated retrieval-engine optimization
          >
    infrastructure micro-optimization
