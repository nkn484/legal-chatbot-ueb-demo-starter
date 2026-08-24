"""No-DB tests for Phase B.1 content-safe diagnostic primitives."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from legal_chatbot.diagnostics.phase_b1_retrieval_engine import (
    LaneEvidence,
    RootCauseCode,
    aggregate_root_cause,
    classify_lane,
    combine_fts_lane_rows,
    gate_b1,
    parse_tsquery_structure,
    percentile,
    prior_phase_b_8425_breakdown,
    q6_trace,
    safe_plan_summary,
    semantic_latency_root,
    write_reports,
)


def _evidence(**changes: Any) -> LaneEvidence:
    values = dict(
        config_matches_simple=True,
        gin_index_valid=True,
        natural_unfiltered_rows=1,
        natural_filtered_rows=1,
        natural_unfiltered_expected=True,
        natural_filtered_expected=True,
        collapsed_expected=True,
        fused_expected=True,
        or_expected=True,
    )
    values.update(changes)
    return LaneEvidence(**values)  # type: ignore[arg-type]


def test_classifier_follows_approved_precedence() -> None:
    assert classify_lane(_evidence(config_matches_simple=False)) is RootCauseCode.CONFIG_MISMATCH
    assert (
        classify_lane(_evidence(natural_filtered_expected=False)) is RootCauseCode.FILTER_EXCLUSION
    )
    assert (
        classify_lane(_evidence(collapsed_expected=False)) is RootCauseCode.IDENTITY_COLLAPSE_LOSS
    )
    assert classify_lane(_evidence(fused_expected=False)) is RootCauseCode.FUSION_LOSS
    assert (
        classify_lane(
            _evidence(
                natural_filtered_expected=False, natural_unfiltered_expected=False, or_expected=True
            )
        )
        is RootCauseCode.QUERY_CONSTRUCTION_FAILURE
    )
    assert (
        classify_lane(
            _evidence(
                natural_filtered_expected=False,
                natural_unfiltered_expected=False,
                or_expected=False,
            )
        )
        is RootCauseCode.FTS_NO_MATCH
    )


def test_tsquery_structure_returns_counts_but_not_tokens() -> None:
    safe = parse_tsquery_structure("'private' & 'lexeme'", source_question="UEB ÁBC 2026")
    assert safe.lexeme_count == 2
    assert safe.and_operator_count == 1
    assert safe.accented_token_count == 1
    assert "private" not in json.dumps(safe.safe())


def test_plan_parser_only_retains_allowlisted_summary_and_limit_evidence() -> None:
    plan = safe_plan_summary(
        [
            {
                "Planning Time": 1.2,
                "Execution Time": 3.4,
                "Plan": {
                    "Node Type": "Limit",
                    "Plans": [
                        {
                            "Node Type": "Bitmap Heap Scan",
                            "Actual Rows": 2,
                            "Plans": [
                                {
                                    "Node Type": "Bitmap Index Scan",
                                    "Index Name": "allowed_gin",
                                    "Actual Rows": 2,
                                    "Shared Hit Blocks": 4,
                                }
                            ],
                        }
                    ],
                },
            }
        ]
    )
    assert plan.limit_above_scan is True
    assert plan.index_names == ("allowed_gin",)
    assert "Plans" not in json.dumps(plan.safe())


def test_percentile_and_gate_reject_incomplete_evidence() -> None:
    assert percentile((1, 2, 100), 95) == 100
    rows: tuple[dict[str, object], ...] = (
        {"lane": "CONTENT_FTS", "classification": "FTS_NO_MATCH"},
        {"lane": "TITLE_FTS", "classification": "OTHER"},
    )
    assert (
        gate_b1(
            lane_rows=rows,
            lane_aggregates={
                "CONTENT_FTS": {"primary": "FTS_NO_MATCH", "decisive": True},
                "TITLE_FTS": {"primary": "MIXED", "decisive": False},
            },
            complete_fields={"fts": True, "q6": True, "counts": False},
        )
        == "NO_GO_B1_INCONCLUSIVE"
    )


def test_gate_passes_only_fully_classified_fixture() -> None:
    rows: tuple[dict[str, object], ...] = (
        {"lane": "CONTENT_FTS", "classification": "FTS_NO_MATCH"},
        {"lane": "TITLE_FTS", "classification": "FTS_QUERY_CONSTRUCTION_FAILURE"},
    )
    assert (
        gate_b1(
            lane_rows=rows,
            lane_aggregates={
                "CONTENT_FTS": {"primary": "FTS_NO_MATCH", "decisive": True},
                "TITLE_FTS": {
                    "primary": "FTS_QUERY_CONSTRUCTION_FAILURE",
                    "decisive": True,
                },
            },
            complete_fields={"fts": True, "q6": True, "counts": True, "flags": True},
        )
        == "PASS_ROOT_CAUSE_PROVEN"
    )


def test_reports_are_content_free_and_partial_safe(tmp_path: Path) -> None:
    markdown, report_json = tmp_path / "root.md", tmp_path / "root.json"
    result = {"gate": "NO_GO_B1_INCONCLUSIVE", "lane_rows": [], "partial_failure": "SAFE_EXCEPTION"}
    write_reports(result, markdown, report_json)
    assert markdown.exists() and report_json.exists()
    assert "question" not in report_json.read_text(encoding="utf-8").casefold()


def test_reports_allow_safe_plan_summary_but_reject_private_fields(tmp_path: Path) -> None:
    markdown, report_json = tmp_path / "root.md", tmp_path / "root.json"
    result = {
        "gate": "PASS_ROOT_CAUSE_PROVEN",
        "fts_aggregates": {"TITLE_FTS": {}, "CONTENT_FTS": {}},
        "latency": {"aggregates": {}},
        "q6": {"trace": []},
        "natural_plan_summary": {"root_node_type": "Limit"},
        "invariants": {"quality_query_planner_enabled": False},
        "distribution": {RootCauseCode.QUERY_CONSTRUCTION_FAILURE.value: 1},
    }
    write_reports(result, markdown, report_json)
    assert report_json.exists()
    write_reports(
        {"natural_plan_summary": {}, "sql_ms": 1, "query_count": 1}, markdown, report_json
    )
    with pytest.raises(ValueError, match="unsafe report field"):
        write_reports({"question": "private"}, markdown, report_json)
    with pytest.raises(ValueError, match="unsafe report field"):
        write_reports({"raw_query": "private"}, markdown, report_json)
    with pytest.raises(ValueError, match="unsafe report field"):
        write_reports({"question_text": "private"}, markdown, report_json)


def test_prior_breakdown_and_q6_trace_are_safe_and_bounded(tmp_path: Path) -> None:
    prior_path = tmp_path / "prior.json"
    prior_path.write_text(
        json.dumps(
            {
                "pool_measurements": [{"p95_latency_ms": 8425.5}],
                "set_a": [
                    {
                        "retrieval_eval_ms": 8425.5,
                        "embedding_ms": 4000,
                        "reader_ms": 4400,
                        "ranking_ms": 25,
                        "end_to_end_ms": 8425.5,
                        "explain_query_count": 3,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    prior = prior_phase_b_8425_breakdown(prior_path)
    assert prior["original_p95_ms"] == 8425.5
    assert prior["retrieval_eval_explain_included"] is False
    assert prior["data_lane_elapsed_ms"] == 4400.5
    assert prior["reader_wall_explain_included"] is True

    trace = q6_trace(
        expected_numbers=("a", "b", "c", "d"), diagnostic=(), pool20=(), final3=()
    )
    assert len(trace) == 4
    assert all(row["rejection_reason"] == "NOT_IN_DIAGNOSTIC_TOP50" for row in trace)


def test_semantic_root_uses_only_safe_plan_and_timing_facts() -> None:
    summary = safe_plan_summary(
        {"Plan": {"Node Type": "Limit", "Plans": [{"Node Type": "Seq Scan"}]}}
    )
    exact = SimpleNamespace(
        label="EXACT_SEMANTIC_TOP8_SCANS_DISABLED",
        plan=summary,
        hnsw_index_used=False,
        limit_evidence=True,
    )
    ann = SimpleNamespace(
        label="ANN_CONTROL_SEMANTIC_TOP50_SCANS_ENABLED",
        plan=summary,
        hnsw_index_used=True,
        limit_evidence=True,
    )
    latency = SimpleNamespace(
        cases=(SimpleNamespace(plans=(exact, ann)),),
        aggregates={
            "phase4_sql_ms": {"p95_ms": 10.0},
            "diagnostic_semantic_ms": {"p95_ms": 20.0},
            "explain_wall_ms": {"p95_ms": 30.0},
            "explain_overhead_ms": {"p95_ms": 15.0},
        },
    )
    root = semantic_latency_root(latency)
    assert root["code"] == "SEMANTIC_EXACT_SCAN_FORCED_SEQSCAN_ANN_CAPABILITY_CONFIRMED"
    assert root["dominant_controlled_data_stage_p95"] == "diagnostic_semantic_ms"
    assert root["explain_wall_p95_ms"] == 30.0


def test_combined_probe_fakes_produce_per_lane_evidence_and_a_complete_gate() -> None:
    plan = safe_plan_summary({"Plan": {"Node Type": "Limit", "Plans": [{"Node Type": "Seq Scan"}]}})
    probe = SimpleNamespace(
        natural_unfiltered_rows=1,
        natural_filtered_rows=0,
        or_filtered_rows=1,
        natural_unfiltered_expected=True,
        natural_filtered_expected=False,
        or_filtered_expected=True,
        natural_filtered_plan=plan,
        or_filtered_plan=plan,
        actual_index_used=False,
        or_filtered_index_used=False,
        index_capability_used=True,
    )
    fts = SimpleNamespace(
        inventory=SimpleNamespace(
            config_matches_simple=True, content_gin_valid=True, title_gin_valid=True
        ),
        cases=(SimpleNamespace(case_id="Q01", content=probe, title=probe),),
    )
    latency = SimpleNamespace(
        cases=(
            SimpleNamespace(
                case_id="Q01",
                diagnostic=SimpleNamespace(
                    lane_collapsed_expected={"CONTENT_FTS": False, "TITLE_FTS": False},
                    fused_expected=False,
                ),
            ),
        )
    )

    rows = combine_fts_lane_rows(fts, latency)
    assert [row["lane"] for row in rows] == ["CONTENT_FTS", "TITLE_FTS"]
    assert all(row["classification"] == RootCauseCode.FILTER_EXCLUSION.value for row in rows)
    aggregate = aggregate_root_cause(rows, "CONTENT_FTS")
    assert aggregate["primary"] == RootCauseCode.FILTER_EXCLUSION.value
    assert aggregate["decisive"] is True
    assert (
        gate_b1(
            lane_rows=rows,
            lane_aggregates={
                "CONTENT_FTS": aggregate,
                "TITLE_FTS": aggregate_root_cause(rows, "TITLE_FTS"),
            },
            complete_fields={
                "parsed_q01_q10": True,
                "fts_probe_complete": True,
                "latency_probe_complete": True,
                "lane_rows_complete": True,
                "prior_phase_b_8425_available": True,
                "q6_complete": True,
                "set_c_frozen_zero": True,
                "counts_unchanged": True,
                "quality_flags_off": True,
                "reviewed_effects_off": True,
            },
        )
        == "PASS_ROOT_CAUSE_PROVEN"
    )


def test_aggregate_reports_mixed_instead_of_an_other_classification() -> None:
    rows: tuple[dict[str, object], ...] = (
        {"lane": "CONTENT_FTS", "classification": RootCauseCode.FTS_NO_MATCH.value},
        {
            "lane": "CONTENT_FTS",
            "classification": RootCauseCode.QUERY_CONSTRUCTION_FAILURE.value,
        },
    )
    aggregate = aggregate_root_cause(rows, "CONTENT_FTS")
    assert aggregate["primary"] == "MIXED"
    assert aggregate["decisive"] is False
    assert (
        gate_b1(
            lane_rows=rows,
            lane_aggregates={
                "CONTENT_FTS": aggregate,
                "TITLE_FTS": {"primary": RootCauseCode.FTS_NO_MATCH.value, "decisive": True},
            },
            complete_fields={"complete": True},
        )
        == "NO_GO_B1_INCONCLUSIVE"
    )
