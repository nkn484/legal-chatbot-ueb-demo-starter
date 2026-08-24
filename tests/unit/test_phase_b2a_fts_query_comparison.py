"""Pure contract tests for the Phase-B2A FTS query comparison."""

from __future__ import annotations

import pytest

from legal_chatbot.diagnostics.phase_b2a_fts_query_comparison import (
    ComparisonError,
    compare_phase_b2a_reports,
)


def _state() -> dict[str, object]:
    flag_names = (
        "lexical_repair_enabled",
        "semantic_hybrid_enabled",
        "rerank_enabled",
        "metadata_repair_enabled",
        "quality_repair_enabled",
        "quality_title_search_enabled",
        "quality_hybrid_fusion_enabled",
        "quality_query_planner_enabled",
        "quality_dynamic_evidence_enabled",
        "quality_repair_retrieval_enabled",
    )
    counts = {
        "reviewed_effect_imports": 0,
        "reviewed_effect_families": 0,
        "reviewed_effect_assertions": 0,
        "reviewed_effect_events": 0,
        "retrieval_runs": 17,
        "citations": 16,
    }
    return {
        "before_counts": counts,
        "after_counts": dict(counts),
        "counts_unchanged": True,
        "reviewed_effect_registry_zero": True,
        "flags": {
            "defaults": {**{name: False for name in flag_names}, "quality_strategy": "disabled"},
            "active": {**{name: False for name in flag_names}, "quality_strategy": "disabled"},
            "static_runtime": {
                "runtime_service_imports_reviewed_effects": False,
                "runtime_service_imports_quality_execution": False,
            },
            "quality_defaults_off": True,
            "quality_active_off": True,
            "reviewed_effects_off": True,
            "flags_off": True,
        },
    }


def _report(mode: str, *, content_hits: int = 0, content_unique: int = 0) -> dict[str, object]:
    case_ids = {
        "A": [f"Q{value:02d}" for value in range(1, 11)],
        "B": [f"B-Q{value:02d}-{index:02d}" for value in range(1, 11) for index in range(1, 4)],
        "C": [f"C-{value:02d}" for value in range(1, 25)],
    }
    metadata = []
    for set_name, values in case_ids.items():
        for case_id in values:
            bounded = mode == "BOUNDED_OR"
            metadata.append(
                {
                    "case_id": case_id,
                    "set_name": set_name,
                    "category": "SAFE",
                    "requested_fts_query_mode": mode,
                    "applied_fts_query_mode": mode,
                    "fts_preparation_query_count": int(bounded),
                    "fts_preparation_elapsed_ms": 2.0 if bounded else 0.0,
                    "bounded_or_selected_lexeme_count": 2 if bounded else 0,
                    "bounded_or_source_lexeme_count": 2 if bounded else 0,
                    "bounded_or_truncated": False,
                    "bounded_or_empty_query": False,
                    "bounded_or_natural_fallback_used": False,
                    "data_query_count": 5 if bounded else 4,
                    "explain_query_count": 1,
                    "query_count": 6 if bounded else 5,
                    "reader_ms": 10.0,
                    "retrieval_eval_ms": 11.0,
                    "transaction_elapsed_ms": 9.0,
                }
            )
    a_rows = []
    for case_id in case_ids["A"]:
        for pool in (8, 12, 16, 20):
            a_rows.append(
                {
                    "case_id": case_id,
                    "pool_size": pool,
                    "candidate_hits": content_hits,
                    "candidate_identity_count": 4,
                    "nonexpected_candidate_count": 3,
                    "final_hits": content_hits,
                    "lane_hits_at_50": {"CONTENT_FTS": content_hits, "TITLE_FTS": 0},
                    "fused_diagnostic_hits_at_50": content_hits,
                    "unique_expected_contribution": {
                        "CONTENT_FTS": content_unique,
                        "TITLE_FTS": 0,
                    },
                    "lexical_unique_rescue_numbers": ["approved-number"] * content_hits,
                    "title_unique_rescue_numbers": [],
                }
            )
    b_rows = [
        {"case_id": case_id, "pool_size": pool, "jaccard": 1.0}
        for case_id in case_ids["B"]
        for pool in (8, 12, 16, 20)
    ]
    c_rows = [
        {"case_id": case_id, "pool_size": pool, "invariant_failures": []}
        for case_id in case_ids["C"]
        for pool in (8, 12, 16, 20)
    ]
    citations = [
        {"resolvable": True, "cleanup": "COMPLETED", "global_counts_match": True}
        for _ in range(136)
    ]
    return {
        "phase_b2a_comparison_contract": {
            "fts_query_mode": mode,
            "case_ids": case_ids,
            "frozen_expected_denominator": 29,
            "pool_sizes": [8, 12, 16, 20],
            "evaluation_source_scope": ["VBQPPL", "VNU", "UEB"],
            "semantic_model_id": "test-model",
            "eligible_expected_inventory_fingerprint": "a" * 64,
        },
        "phase_b2a_state_invariants": _state(),
        "fts_read_metadata": metadata,
        "set_a": a_rows,
        "set_b": b_rows,
        "set_c": c_rows,
        "citation_invariants": citations,
        "pool_measurements": [{"pool_size": pool} for pool in (8, 12, 16, 20)],
        "set_b_summary": {"mean_jaccard": 1.0, "evidence_consistency_rate": 1.0},
    }


def test_comparison_reports_positive_delta_and_mechanical_gate() -> None:
    comparison = compare_phase_b2a_reports(
        _report("NATURAL"), _report("BOUNDED_OR", content_hits=1, content_unique=1)
    )

    assert comparison["mechanical_gate"]["status"] == "PASS_B2A_MEASURED"
    assert comparison["conclusion"] == "POSITIVE_FTS_CONTRIBUTION"
    assert comparison["deltas"]["top50"]["content_expected_hits"] == 10
    assert comparison["candidate"]["cost"]["preparation_total_ms"] == 128.0


def test_comparison_reports_negative_when_repair_has_no_unique_contribution() -> None:
    comparison = compare_phase_b2a_reports(
        _report("NATURAL"), _report("BOUNDED_OR", content_hits=1, content_unique=0)
    )

    assert comparison["mechanical_gate"]["status"] == "PASS_B2A_MEASURED"
    assert comparison["conclusion"] == "NEGATIVE_NO_UNIQUE_CONTRIBUTION"


def test_comparison_reports_no_go_for_safety_or_cost_failure() -> None:
    bounded = _report("BOUNDED_OR", content_hits=1, content_unique=1)
    bounded["set_c"][0]["invariant_failures"] = ["QUERY_COUNT"]  # type: ignore[index]

    comparison = compare_phase_b2a_reports(_report("NATURAL"), bounded)

    assert comparison["mechanical_gate"]["status"] == "NO_GO_SAFETY_OR_COST"
    assert comparison["conclusion"] == "NO_GO_SAFETY_OR_COST"

    costly = _report("BOUNDED_OR", content_hits=1, content_unique=1)
    costly["fts_read_metadata"][0]["data_query_count"] = 13  # type: ignore[index]
    costly["fts_read_metadata"][0]["query_count"] = 14  # type: ignore[index]
    cost_comparison = compare_phase_b2a_reports(_report("NATURAL"), costly)
    assert cost_comparison["mechanical_gate"]["status"] == "NO_GO_SAFETY_OR_COST"
    assert cost_comparison["conclusion"] == "NO_GO_SAFETY_OR_COST"


@pytest.mark.parametrize("failure", ("changed_count", "registry", "active_flag"))
def test_comparison_keeps_complete_non_off_state_evidence_as_no_go(failure: str) -> None:
    bounded = _report("BOUNDED_OR", content_hits=1, content_unique=1)
    state = bounded["phase_b2a_state_invariants"]  # type: ignore[index]
    if failure == "changed_count":
        state["after_counts"]["citations"] += 1  # type: ignore[index]
    elif failure == "registry":
        state["after_counts"]["reviewed_effect_imports"] = 1  # type: ignore[index]
    else:
        state["flags"]["active"]["quality_repair_enabled"] = True  # type: ignore[index]

    comparison = compare_phase_b2a_reports(_report("NATURAL"), bounded)

    assert comparison["mechanical_gate"]["status"] == "NO_GO_SAFETY_OR_COST"
    assert comparison["conclusion"] == "NO_GO_SAFETY_OR_COST"


def test_comparison_rejects_mismatched_corpus_or_incomplete_mode_metadata() -> None:
    bounded = _report("BOUNDED_OR")
    bounded["phase_b2a_comparison_contract"]["eligible_expected_inventory_fingerprint"] = "b" * 64  # type: ignore[index]
    with pytest.raises(ComparisonError, match="not comparable"):
        compare_phase_b2a_reports(_report("NATURAL"), bounded)

    incomplete = _report("BOUNDED_OR")
    del incomplete["fts_read_metadata"][0]["bounded_or_empty_query"]  # type: ignore[index]
    with pytest.raises(ComparisonError, match="fields are incomplete"):
        compare_phase_b2a_reports(_report("NATURAL"), incomplete)


def test_comparison_rejects_private_report_fields_and_emits_no_input_identifiers() -> None:
    natural = _report("NATURAL")
    natural["question"] = "private query"  # type: ignore[index]
    with pytest.raises(ComparisonError, match="unsafe report field"):
        compare_phase_b2a_reports(natural, _report("BOUNDED_OR"))

    comparison = compare_phase_b2a_reports(
        _report("NATURAL"), _report("BOUNDED_OR", content_hits=1, content_unique=1)
    )
    serialized = str(comparison)
    assert "approved-number" not in serialized
    assert "B-Q01-01" not in serialized
