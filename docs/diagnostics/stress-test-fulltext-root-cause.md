# Prompt-01 fulltext root-cause diagnostic

## Methodology caveat
B_REVIEW_TOPIC_CONTROL uses review-sheet topic and C_ORACLE_SOURCE_SCOPE_CONTROL uses oracle expected-inventory source labels. They are controlled diagnostic sensitivity tests, not independent generalization or production-design evidence. `merged_diagnostic_top50` is RRF across A/B/C controls and shows candidate availability only; it is not production recall.

## Aggregate availability
Production-equivalent A semantic top50 availability: 24/29.
Controlled merged diagnostic top50 availability: 27/29.
Production-equivalent final top3 availability: 6/29.

| Q | Expected direct docs | Found top50? | Found final? | Wrong docs selected | Failure stage | Root cause | Confidence |
|---|---|---|---|---|---|---|---|
| Q01 | 08/2021/TT-BGDĐT; 3626/QĐ-ĐHQGHN; 2725/QĐ-ĐHKT | 3/3 | 1/3 | 2795/QĐ-ĐHKT; 5115/QĐ-ĐHQGHN | FINAL_SELECTION;RANK_CUTOFF | CANDIDATE_WINDOW_MISS;EXPECTED_DOCUMENT_FOUND_FINAL;NUMBER_NORMALIZATION_MISMATCH;REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT;REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT | HIGH |
| Q02 | 216/QĐ-ĐHQGHN; 812/QĐ-ĐHKT; 325/QĐ-ĐHKT | 3/3 | 1/3 | 1144/QĐ-ĐHKT; 1694/QĐ-ĐHKT | FINAL_SELECTION;RANK_CUTOFF | CANDIDATE_WINDOW_MISS;EXPECTED_DOCUMENT_FOUND_FINAL | HIGH |
| Q03 | 5946/QĐ-ĐHQGHN; 1107/QĐ-ĐHKT; 1818/QĐ-BGDĐT | 2/3 | 0/3 | 3577/QĐ-ĐHKT; 43-HD/BTCTW; 4588/ĐHKT-TCNS | CANDIDATE_SELECTION;RANK_CUTOFF | CANDIDATE_WINDOW_MISS;REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT;TITLE_NOT_SEARCHED_PRODUCTION | HIGH |
| Q04 | 531/QĐ-TTg; 4868/QĐ-ĐHQGHN; 4822/QĐ-ĐHKT | 3/3 | 1/3 | 1630/QĐ-TTg; 2868/QĐ-ĐHQGHN | FINAL_SELECTION;RANK_CUTOFF;RERANK | CANDIDATE_WINDOW_MISS;EXPECTED_DOCUMENT_FOUND_FINAL;RERANK_DEMOTION | HIGH |
| Q05 | 49/2026/TT-BKHCN; 2868/QĐ-ĐHQGHN; 1525/QĐ-ĐHKT | 3/3 | 0/3 | 1101/QĐ-ĐHKT; 3416/QĐ-ĐHQGHN; 3888/QĐ-ĐHQGHN | RANK_CUTOFF | CANDIDATE_WINDOW_MISS | HIGH |
| Q06 | 5858/QĐ-ĐHQGHN; 5097/QĐ-ĐHQGHN; 1666/QĐ-ĐHKT; 1407/QĐ-ĐHKT | 4/4 | 0/4 | 16/NQ-HĐTĐHKT; 4606/UQ-ĐHKT; 821/QĐ-ĐHKT | RANK_CUTOFF;RERANK | CANDIDATE_WINDOW_MISS;DUPLICATE_CATALOG_IDENTITY;RERANK_DEMOTION;REVIEW_HYPOTHESIS_MULTI_INTENT_CAPABILITY_ABSENT;REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT | HIGH |
| Q07 | 3638/QĐ-ĐHQGHN; 2458/QĐ-ĐHQGHN; 3083/QĐ-ĐHKT | 3/3 | 1/3 | 1144/QĐ-ĐHKT; 4555/QĐ-ĐHQGHN | FINAL_SELECTION;RANK_CUTOFF | CANDIDATE_WINDOW_MISS;DUPLICATE_CATALOG_IDENTITY;EXPECTED_DOCUMENT_FOUND_FINAL;REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT | HIGH |
| Q08 | 3636/QĐ-ĐHQGHN; 4852/QĐ-ĐHKT | 2/2 | 0/2 | 2566/QĐ-ĐHKT; 2803/QĐ-ĐHKT | RANK_CUTOFF | CANDIDATE_WINDOW_MISS;DUPLICATE_CATALOG_IDENTITY;INSUFFICIENCY_RECHECK_REQUIRED_CANDIDATE_PRESENT | HIGH |
| Q09 | 2929/QĐ-ĐHQGHN; 1768/QĐ-ĐHKT | 1/2 | 1/2 | 4868/QĐ-ĐHQGHN; 4889/QĐ-ĐHQGHN | CANDIDATE_SELECTION;FINAL_SELECTION | DIRECT_DOCUMENT_MISS;EXPECTED_DOCUMENT_FOUND_FINAL | HIGH |
| Q10 | 08/2021/TT-BGDĐT; 3626/QĐ-ĐHQGHN; 2725/QĐ-ĐHKT | 3/3 | 1/3 | 2841/QĐ-ĐHKT; 32/QĐ-ĐHQGHN | FINAL_SELECTION;RERANK | EXPECTED_DOCUMENT_FOUND_FINAL;NUMBER_NORMALIZATION_MISMATCH;RERANK_DEMOTION;REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT | HIGH |

## Q01
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q01): top50=3/3, final=1/3, codes=CANDIDATE_WINDOW_MISS;EXPECTED_DOCUMENT_FOUND_FINAL;NUMBER_NORMALIZATION_MISMATCH;REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT;REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT. Code inspection confirms capability absence; case applicability is review-guided and requires repair evaluation. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q02
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q02): top50=3/3, final=1/3, codes=CANDIDATE_WINDOW_MISS;EXPECTED_DOCUMENT_FOUND_FINAL. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q03
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=1, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q03): top50=2/3, final=0/3, codes=CANDIDATE_WINDOW_MISS;REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT;TITLE_NOT_SEARCHED_PRODUCTION. Code inspection confirms capability absence; case applicability is review-guided and requires repair evaluation. An expected candidate was measured outside the final candidate window. The expected identity was observed only in diagnostic title metadata.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q04
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q04): top50=3/3, final=1/3, codes=CANDIDATE_WINDOW_MISS;EXPECTED_DOCUMENT_FOUND_FINAL;RERANK_DEMOTION. A pre-rerank expected candidate was demoted before final selection. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q05
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=1, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q05): top50=3/3, final=0/3, codes=CANDIDATE_WINDOW_MISS. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q06
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=4, indexed expected identities=4.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=4, indexed expected identities=4.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=4, indexed expected identities=4.
D_EXACT_NUMBER_CONTROL candidates: 4; expected-doc hits=4.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q06): top50=4/4, final=0/4, codes=CANDIDATE_WINDOW_MISS;DUPLICATE_CATALOG_IDENTITY;RERANK_DEMOTION;REVIEW_HYPOTHESIS_MULTI_INTENT_CAPABILITY_ABSENT;REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT. Code inspection confirms capability absence; case applicability is review-guided and requires repair evaluation. A pre-rerank expected candidate was demoted before final selection. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q07
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q07): top50=3/3, final=1/3, codes=CANDIDATE_WINDOW_MISS;DUPLICATE_CATALOG_IDENTITY;EXPECTED_DOCUMENT_FOUND_FINAL;REVIEW_HYPOTHESIS_VERSION_STATUS_CAPABILITY_ABSENT. Code inspection confirms capability absence; case applicability is review-guided and requires repair evaluation. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q08
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=2.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=2.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=2, indexed expected identities=2.
D_EXACT_NUMBER_CONTROL candidates: 2; expected-doc hits=2.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q08): top50=2/2, final=0/2, codes=CANDIDATE_WINDOW_MISS;DUPLICATE_CATALOG_IDENTITY;INSUFFICIENCY_RECHECK_REQUIRED_CANDIDATE_PRESENT. Diagnostic candidate availability requires insufficiency recheck; final answer was not run. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q09
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=1, indexed expected identities=2.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=1, indexed expected identities=2.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=1, indexed expected identities=2.
D_EXACT_NUMBER_CONTROL candidates: 2; expected-doc hits=2.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q09): top50=1/2, final=1/2, codes=DIRECT_DOCUMENT_MISS;EXPECTED_DOCUMENT_FOUND_FINAL. An expected candidate was measured outside the final candidate window.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Q10
### A-D evidence summaries
A/B/C query text: NOT_EMITTED_BY_PRIVACY_POLICY; D: CONTROLLED_INPUT_REFERENCE.
A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
B_REVIEW_TOPIC_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
C_ORACLE_SOURCE_SCOPE_CONTROL candidates: lexical=0, semantic=50, lexical expected hits=0, semantic expected hits=3, indexed expected identities=3.
D_EXACT_NUMBER_CONTROL candidates: 3; expected-doc hits=3.
Selected evidence is diagnostic-only, not persisted citation evidence.
Measured explanation (Q10): top50=3/3, final=1/3, codes=EXPECTED_DOCUMENT_FOUND_FINAL;NUMBER_NORMALIZATION_MISMATCH;RERANK_DEMOTION;REVIEW_HYPOTHESIS_LEGAL_HIERARCHY_CAPABILITY_ABSENT. Code inspection confirms capability absence; case applicability is review-guided and requires repair evaluation. A pre-rerank expected candidate was demoted before final selection.
Code paths: `documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_rerank`.
### Required prompt trace fields
Trace: `{"intent": "NOT_IMPLEMENTED", "entities": "NOT_IMPLEMENTED", "org": "NOT_IMPLEMENTED", "legal_topics": "NOT_IMPLEMENTED", "sub_intents": "NOT_IMPLEMENTED", "query_plan": "NOT_IMPLEMENTED", "expanded_queries": "NOT_EMITTED_BY_PRIVACY_POLICY", "corpus_insight_policy": "NOT_IMPLEMENTED"}`

## Blockers
NONE

## Code path references
`documents/retrieval_repository.py:_select_candidates`; `documents/hybrid_retrieval_repository.py:_select_semantic`; `documents/reranked_semantic_repository.py:_read_candidates/_rerank`; `diagnostics/fulltext_root_cause.py`.

## Limitations
Reports include approved corpus metadata and controlled expected identities, but exclude raw questions, normalized/generated query text, chunks, answers, URLs, UUIDs, hydrated text, and prompts/model payloads. Review classifications are hypothesis selectors only; Q1/Q2/Q5/Q6/Q8/Q10 receive no special claim unless measured above.
