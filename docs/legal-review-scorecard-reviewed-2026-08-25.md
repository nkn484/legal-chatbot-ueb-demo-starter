# Independent Legal Review Scorecard - Set A
**Review date:** 2026-08-25
**Candidate:** `stress-2026-08-25-hybrid-provider-healthy.xlsx`
**Candidate SHA-256:** `D28E3156CEC459CBBB06882D0DA31B55B043C4BA8E6ADCA13627F3F090A09C62`
**Reviewer role:** Independent legal-quality reviewer (decision-support readiness)
**Rubric:** Correctness 4.0 + Authority/Appplicability 2.5 + Completeness 2.5 + Traceability/Inference Discipline 1.0
**PASS threshold:** >= 7.0
**Release target:** average >= 8.50 and >= 9/10 PASS

> This review does not treat `ANSWER_GROUNDED`, citation immutability, or citation resolvability as proof of legal correctness. Scores assess whether the candidate answer actually addresses the legal issue with appropriate authority, adequate coverage, and controlled inference.

| Case | Correctness /4.0 | Authority /2.5 | Completeness /2.5 | Traceability /1.0 | Total /10 | PASS >=7 | Claim/citation findings |
|---|---:|---:|---:|---:|---:|---|---|
| Q01 | 2.2 | 0.5 | 0.5 | 0.8 | **4.0** | FAIL | Answer appropriately admits insufficiency, but does not answer general UEB conditions. Final evidence contains no expected governing document. The Troy-program rule is explicitly program-specific and cannot be generalized to ordinary UEB students. |
| Q02 | 3.0 | 1.3 | 1.7 | 0.8 | **6.8** | FAIL | 812/QĐ-ĐHKT is directly relevant internally, but national/VNU authority expected for personal-data collection/use/sharing is absent. Several broad legal claims are presented without direct national-law citation; treating all learner personal information as “sensitive” is potentially over-broad without qualification. |
| Q03 | 3.0 | 1.1 | 1.7 | 0.8 | **6.6** | FAIL | Useful procedural description and appropriate admission that individual criteria are incomplete. However, none of the expected governing documents reaches final evidence; unit-function and annual-guidance materials cannot substitute for the full governing criteria/applicability framework. |
| Q04 | 2.8 | 1.2 | 1.5 | 0.7 | **6.2** | FAIL | 4822/QĐ-ĐHKT is relevant, but national/VNU authority expected for state-secret classification is missing. The answer risks overstatement when suggesting the head of the school may determine secrecy level without clearly conditioning this on statutory state-secret lists and competent classification authority. |
| Q05 | 1.8 | 0.2 | 0.3 | 0.7 | **3.0** | FAIL | No expected governing document is retrieved. The answer safely admits insufficiency, but generic finance principles are drawn from documents about scientist clubs, UEB Visa and researcher working regimes rather than the strategic R&D task regime asked about. |
| Q06 | 2.8 | 1.0 | 1.2 | 0.8 | **5.8** | FAIL | Only 1666/QĐ-ĐHKT matches the expected authority set. The answer correctly limits the UEB Shop delegation, but still gives a generalized procurement sequence while key VNU/UEB authority and inventory-process documents are absent. Not reliable enough for an operational purchasing decision. |
| Q07 | 2.6 | 0.7 | 1.5 | 0.7 | **5.5** | FAIL | Detailed doctoral rules are given, but final evidence uses 4555/QĐ-ĐHQGHN rather than the expected current VNU/UEB governing documents. Without verified current effect/version relationship, concrete duration and dismissal rules are not safe to treat as current UEB decision authority. |
| Q08 | 1.6 | 0.1 | 0.2 | 0.6 | **2.5** | FAIL | Final evidence is entirely the UEB Visa regulation, which is not a master's training regulation. The answer appropriately refuses to invent the missing rules, but it does not answer the legal question and demonstrates a severe retrieval/authority miss. |
| Q09 | 3.5 | 1.9 | 1.9 | 0.8 | **8.1** | PASS | 1768/QĐ-ĐHKT directly governs UEB records/archives and supports the core answer. The state-secret VNU document is relevant only to the confidential-record caveat. Missing expected VNU records authority reduces completeness but does not defeat the core UEB answer. |
| Q10 | 3.4 | 2.0 | 1.8 | 0.8 | **8.0** | PASS | 08/2021/TT-BGDĐT and 3626/QĐ-ĐHQGHN are directly relevant and provide a substantially stronger authority chain. The third citation is an unrelated MBA joint-program document, and UEB-specific procedure remains unavailable; the answer correctly qualifies that gap. |

## Result

- **Average legal-quality score:** **5.85 / 10**
- **PASS:** **2 / 10**
- **FAIL:** **8 / 10**
- **Target average >= 8.50:** **NOT MET**
- **Target PASS >= 9/10:** **NOT MET**

## Reviewer decision

# **NO_GO**

The candidate is technically grounded but is **not suitable for a legal demo carrying an accuracy/decision-support commitment**.

### Principal release blockers

1. **Groundedness is not legal authority.** Several answers are grounded in documents that are irrelevant, overly narrow, or not the controlling authority for the question.
2. **Final evidence coverage is materially incomplete.** Q01, Q03, Q05, Q07 and Q08 have zero expected-document hits in final evidence; other cases retain only part of the governing evidence set.
3. **Fixed three-evidence selection is insufficient for multi-part legal questions.**
4. **Authority/applicability/version control is not mature enough.** A semantically relevant or historically valid regulation is not automatically the currently applicable rule.
5. **Claim-to-citation verification is too coarse.** The artifact identifies documents/URLs but does not expose a reviewer-friendly article/paragraph-level mapping for every material claim.
6. **Corpus gaps remain material.** Missing/quarantined governing documents cannot be replaced with inference from loosely related documents.

### Positive findings

- The model frequently **abstains or qualifies** when evidence is insufficient instead of fabricating a complete rule.
- Q09 and Q10 demonstrate that when direct authority survives final selection, the system can produce useful, structured legal answers.
- Citation/provenance integrity and provider health are useful technical controls, but they are supporting controls rather than legal-quality proof.

## Required remediation before re-review

1. Improve direct-authority retrieval and source-tier coverage.
2. Prevent irrelevant program-specific/internal administrative documents from substituting for governing legal rules.
3. Implement evidence completeness by material sub-intent and allow bounded dynamic evidence where justified.
4. Add applicability/version checks or explicit uncertainty treatment before stating concrete legal consequences.
5. Provide article/paragraph-level claim-citation mapping for reviewer verification.
6. Re-run Set A and obtain an independent legal score of **>=8.50 average and >=9/10 PASS** before any accuracy commitment.

## Review limitation

This scorecard is based on the candidate answers, cited-document identities/metadata, corpus expected-document inventory, release dossier, and available source inspection. Several Drive PDFs do not expose machine-readable text through the connector, so this review does **not** certify every clause of every cited PDF. That limitation does not change the `NO_GO` result because the observable answer/evidence failures already prevent the frozen release target from being met.
