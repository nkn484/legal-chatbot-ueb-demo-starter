# Phase B.1 retrieval-engine root cause

## Evidence protocol
The embedding model and database candidate paths were warmed once with an internal constant before a fixed, sequential ten-case pass. Reported p50/p95 values are descriptive nearest-rank statistics, not repeated-trial confidence estimates.

## Actual FTS configuration/index inventory
{"config_matches_simple": true, "content_gin_valid": true, "title_gin_valid": true, "indexes": [{"name": "ix_document_chunks_search_vector_gin", "exists": true, "valid": true, "ready": true, "gin": true}, {"name": "ix_document_versions_title_search_vector_gin", "exists": true, "valid": true, "ready": true, "gin": true}]}

## TITLE_FTS root cause
{"distribution": {"FTS_NO_MATCH": 3, "FTS_QUERY_CONSTRUCTION_FAILURE": 7}, "primary": "FTS_QUERY_CONSTRUCTION_FAILURE", "decisive": true}

## CONTENT_FTS root cause
{"distribution": {"FTS_QUERY_CONSTRUCTION_FAILURE": 10}, "primary": "FTS_QUERY_CONSTRUCTION_FAILURE", "decisive": true}

Natural conjunction misses followed by bounded OR-control recovery are classified as query-construction recall limitations; this does not assert that OR is the intended production query semantics.

## Per-case FTS evidence
| Case | Lane | Classification | Natural rows | Natural expected | Collapsed expected | Fused expected | OR expected | Index used |
|---|---|---|---:|---|---|---|---|---|
| Q01 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q01 | TITLE_FTS | FTS_NO_MATCH | 0 | False | False | True | False | True |
| Q02 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q02 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q03 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q03 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q04 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q04 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q05 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q05 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q06 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q06 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q07 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q07 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q08 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q08 | TITLE_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | True |
| Q09 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q09 | TITLE_FTS | FTS_NO_MATCH | 0 | False | False | True | False | True |
| Q10 | CONTENT_FTS | FTS_QUERY_CONSTRUCTION_FAILURE | 0 | False | False | True | True | False |
| Q10 | TITLE_FTS | FTS_NO_MATCH | 0 | False | False | True | False | True |

## Original cold nearest-rank p95 breakdown
{"available": true, "original_latency_statistic": "COLD_NEAREST_RANK_P95", "original_cold_nearest_rank_p95_ms": 8425.502, "original_p95_ms": 8425.502, "retrieval_eval_formula": "embedding_ms + data_lane_elapsed_ms + ranking_ms", "embedding_ms": 4459.991, "data_lane_elapsed_ms": 3959.381, "ranking_ms": 6.13, "component_sum_ms": 8425.502, "retrieval_eval_explain_included": false, "reader_wall_with_explain_ms": 6841.028, "end_to_end_with_explain_ms": 11307.172, "reader_wall_explain_included": true, "timings_are_not_all_additive": true}

The frozen retrieval-evaluation p95 excludes EXPLAIN and follows the evaluator formula. Reader wall/end-to-end timings that include EXPLAIN are separate, non-additive observations.

## Model-and-database-warmed single-pass p50/p95
| Stage | p50 ms | p95 ms |
|---|---:|---:|
| embedding_ms | 10.898 | 31.485 |
| phase4_transaction_setup_ms | 2.694 | 2.966 |
| phase4_sql_ms | 325.711 | 368.045 |
| phase4_collapse_ms | 0.263 | 0.38 |
| phase4_total_ms | 330.161 | 372.734 |
| diagnostic_semantic_ms | 312.204 | 3135.955 |
| diagnostic_content_ms | 264.63 | 397.828 |
| diagnostic_title_ms | 1.039 | 1.67 |
| diagnostic_collapse_ms | 0.808 | 1.336 |
| diagnostic_fusion_ms | 0.302 | 0.527 |
| diagnostic_transaction_other_ms | 5.978 | 7.391 |
| diagnostic_total_ms | 593.075 | 3192.271 |
| explain_wall_ms | 3471.452 | 3628.912 |
| explain_overhead_ms | 2895.166 | 3003.285 |
| analyzer_ms | 0.0 | 0.0 |
| hydration_ms | 0.0 | 0.0 |

Query-count accounting: {"embedding_call_count": 11, "timed_embedding_call_count": 10, "database_warmup_call_count": 3, "database_warmup_data_query_count": 7, "database_warmup_explain_query_count": 3, "phase4_exact_path_count": 10, "diagnostic_no_explain_reader_call_count": 10, "diagnostic_with_explain_reader_call_count": 10, "plan_query_count": 30, "hnsw_capability_query_count": 1, "data_query_count": 70, "explain_query_count": 60, "duplicate_query_count": 30}

## Semantic plan/capability evidence
{"code": "SEMANTIC_EXACT_SCAN_FORCED_SEQSCAN_ANN_CAPABILITY_CONFIRMED", "exact_scan_mode": "INDEX_AND_BITMAP_SCANS_DISABLED_BY_DIAGNOSTIC", "exact_hnsw_absence_is_planner_failure": false, "exact_scans_disabled_seq_scan": true, "exact_scans_disabled_plan_count": 20, "exact_seq_scan_plan_count": 20, "exact_index_scan_plan_count": 0, "exact_index_names": [], "exact_hnsw_actual": false, "ann_control_plan_count": 10, "ann_control_hnsw_actual": true, "ann_control_scope": "BARE_CHUNK_EMBEDDING_CAPABILITY_NOT_PRODUCTION_EQUIVALENT", "exact_limit_above_scan": true, "ann_control_limit_above_scan": true, "model_and_database_warmed_single_pass_case_count": 10, "descriptive_nearest_rank_p95": true, "dominant_controlled_data_stage_p95": "diagnostic_semantic_ms", "dominant_controlled_data_stage_p95_ms": 3135.955, "explain_wall_p95_ms": 3628.912, "explain_overhead_p95_ms": 3003.285, "description": "Exact seq scans are diagnostic-by-design; the separate ANN control proves only bare index capability. Timings are descriptive over the fixed ten-case pass."}

Exact-path seq scans are forced by disabled index/bitmap scans. The bare ANN control proves HNSW capability only; it is not production-equivalent planner evidence. Nested plan-summary row/buffer values are not PostgreSQL plan-total resource usage.

## Additional hypothetical Q6 trace (fresh EXPLAIN_FALSE run)
This is not a replay of a frozen Phase-B selected configuration; Phase B had NO_SELECTION.

| Document number | Diagnostic | Pool20 | Final3 | Fusion | Semantic rank | Semantic score | Rejection |
|---|---:|---:|---:|---:|---:|---:|---|
| 5858/qđ-đhqghn | 20 | 20 | None | 0.010309278350515464 | 37 | 0.8622328042984009 | FINAL_TOP3_CUTOFF |
| 5097/qđ-đhqghn | 7 | 7 | None | 0.014084507042253521 | 11 | 0.868828296661377 | FINAL_TOP3_CUTOFF |
| 1666/qđ-đhkt | 3 | 3 | 3 | 0.015873015873015872 | 3 | 0.8790968584476044 | SELECTED_FINAL_TOP3 |
| 1407/qđ-đhkt | 14 | 14 | None | 0.011111111111111112 | 30 | 0.8630127906799316 | FINAL_TOP3_CUTOFF |

Wrong final document numbers: ["4606/uq-đhkt", "16/nq-hđtđhkt"]

## Read-only/default-off invariants
{"case_count": 10, "counts_before": {"reviewed_effect_imports": 0, "reviewed_effect_families": 0, "reviewed_effect_assertions": 0, "reviewed_effect_events": 0, "retrieval_runs": 17, "citations": 16}, "counts_after": {"reviewed_effect_imports": 0, "reviewed_effect_families": 0, "reviewed_effect_assertions": 0, "reviewed_effect_events": 0, "retrieval_runs": 17, "citations": 16}, "counts_unchanged": true, "set_c_zero_from_phase_b": true, "flags": {"defaults": {"lexical_repair_enabled": false, "semantic_hybrid_enabled": false, "rerank_enabled": false, "metadata_repair_enabled": false, "quality_repair_enabled": false, "quality_title_search_enabled": false, "quality_hybrid_fusion_enabled": false, "quality_query_planner_enabled": false, "quality_dynamic_evidence_enabled": false, "quality_repair_retrieval_enabled": false, "quality_strategy_disabled": true}, "static_runtime": {"runtime_service_imports_reviewed_effects": false, "runtime_service_imports_quality_execution": false}, "quality_flags_off": true, "reviewed_effects_off": true, "flags_off": true}, "complete_fields": {"parsed_q01_q10": true, "fts_probe_complete": true, "latency_probe_complete": true, "lane_rows_complete": true, "prior_phase_b_8425_available": true, "semantic_plan_capability_complete": true, "q6_complete": true, "set_c_frozen_zero": true, "counts_unchanged": true, "quality_flags_off": true, "reviewed_effects_off": true}, "root_lanes_classified": true}

## recommended remediation1-3
1. Separately approve an FTS query-construction experiment only where evidence supports it.
2. Investigate exact semantic SQL, index capability, and warm-cache behavior.
3. Establish an evaluation warmup and latency measurement protocol.

## Gate
**PASS_ROOT_CAUSE_PROVEN**

## explicit no tuning
No retrieval, index, SQL, model, or runtime tuning was implemented by this diagnostic.
