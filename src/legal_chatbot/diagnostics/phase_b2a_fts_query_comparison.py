"""Pure, content-free comparison of paired Phase-B2A FTS evaluator reports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import quantiles
from typing import Any

_POOLS = (8, 12, 16, 20)
_SOURCE_SCOPE = ("VBQPPL", "VNU", "UEB")
_DENOMINATOR = 29
_COUNT_NAMES = (
    "reviewed_effect_imports",
    "reviewed_effect_families",
    "reviewed_effect_assertions",
    "reviewed_effect_events",
    "retrieval_runs",
    "citations",
)
_QUALITY_FLAG_NAMES = (
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
    "quality_strategy",
)
_SENSITIVE_KEYS = frozenset(
    {
        "answer",
        "answers",
        "chunk",
        "chunks",
        "credential",
        "credentials",
        "question",
        "questions",
        "raw_plan",
        "sql",
        "tsquery",
        "url",
        "urls",
        "vector",
        "vectors",
    }
)


class ComparisonError(ValueError):
    """Raised when an evaluator artifact is incomplete, unsafe, or not comparable."""


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ComparisonError(f"{name} must be an object")
    return value


def _rows(value: object, name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ComparisonError(f"{name} must be a list of objects")
    return tuple(value)


def _assert_content_free(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                raise ComparisonError(f"unsafe report field: {key}")
            _assert_content_free(child)
    elif isinstance(value, list):
        for child in value:
            _assert_content_free(child)


def _percentile(values: Iterable[float]) -> float:
    data = sorted(values)
    if not data:
        return 0.0
    if len(data) == 1:
        return round(data[0], 3)
    return round(quantiles(data, n=100, method="inclusive")[94], 3)


def _contract(payload: Mapping[str, Any], expected_mode: str) -> Mapping[str, Any]:
    contract = _mapping(payload.get("phase_b2a_comparison_contract"), "comparison contract")
    required = {
        "fts_query_mode",
        "case_ids",
        "frozen_expected_denominator",
        "pool_sizes",
        "evaluation_source_scope",
        "semantic_model_id",
        "eligible_expected_inventory_fingerprint",
    }
    if set(contract) < required:
        raise ComparisonError("comparison contract is incomplete")
    if contract["fts_query_mode"] != expected_mode:
        raise ComparisonError(f"comparison contract mode must be {expected_mode}")
    if contract["frozen_expected_denominator"] != _DENOMINATOR:
        raise ComparisonError("frozen expected denominator mismatch")
    if tuple(contract["pool_sizes"]) != _POOLS:
        raise ComparisonError("frozen pool sizes mismatch")
    if tuple(contract["evaluation_source_scope"]) != _SOURCE_SCOPE:
        raise ComparisonError("evaluation source scope mismatch")
    if not isinstance(contract["semantic_model_id"], str) or not contract["semantic_model_id"]:
        raise ComparisonError("semantic model metadata is incomplete")
    fingerprint = contract["eligible_expected_inventory_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ComparisonError("corpus fingerprint is incomplete")
    case_ids = _mapping(contract["case_ids"], "case IDs")
    if set(case_ids) != {"A", "B", "C"} or any(
        not isinstance(case_ids[name], list) or not case_ids[name] for name in case_ids
    ):
        raise ComparisonError("case IDs are incomplete")
    if tuple(len(case_ids[name]) for name in ("A", "B", "C")) != (10, 30, 24):
        raise ComparisonError("case IDs do not cover the frozen B2A evaluation sets")
    if any(len(set(case_ids[name])) != len(case_ids[name]) for name in case_ids):
        raise ComparisonError("case IDs must be unique within each evaluation set")
    return contract


def _validate_state_invariants(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    state = _mapping(payload.get("phase_b2a_state_invariants"), "state invariants")
    if set(state) < {
        "before_counts",
        "after_counts",
        "counts_unchanged",
        "reviewed_effect_registry_zero",
        "flags",
    }:
        raise ComparisonError("state invariants are incomplete")
    for name in ("before_counts", "after_counts"):
        counts = _mapping(state[name], name)
        if set(counts) != set(_COUNT_NAMES) or any(
            not isinstance(counts[key], int) or isinstance(counts[key], bool) or counts[key] < 0
            for key in _COUNT_NAMES
        ):
            raise ComparisonError("state count snapshot is incomplete")
    flags = _mapping(state["flags"], "state flags")
    if set(flags) < {
        "defaults",
        "active",
        "static_runtime",
        "quality_defaults_off",
        "quality_active_off",
        "reviewed_effects_off",
        "flags_off",
    }:
        raise ComparisonError("state flag evidence is incomplete")
    for name in ("defaults", "active"):
        values = _mapping(flags[name], name)
        if set(values) != set(_QUALITY_FLAG_NAMES):
            raise ComparisonError("quality flag evidence is incomplete")
    static_runtime = _mapping(flags["static_runtime"], "static runtime imports")
    if set(static_runtime) != {
        "runtime_service_imports_reviewed_effects",
        "runtime_service_imports_quality_execution",
    }:
        raise ComparisonError("runtime import evidence is incomplete")
    return state


def _state_invariants_pass(state: Mapping[str, Any]) -> bool:
    flags = _mapping(state["flags"], "state flags")
    before = _mapping(state["before_counts"], "before counts")
    after = _mapping(state["after_counts"], "after counts")
    defaults = _mapping(flags["defaults"], "default flags")
    active = _mapping(flags["active"], "active flags")
    static_runtime = _mapping(flags["static_runtime"], "static runtime imports")
    registry_zero = all(
        before[name] == 0 and after[name] == 0
        for name in _COUNT_NAMES
        if name.startswith("reviewed_effect_")
    )
    quality_defaults_off = not any(defaults[name] for name in _QUALITY_FLAG_NAMES[:-1]) and (
        defaults["quality_strategy"] == "disabled"
    )
    quality_active_off = not any(active[name] for name in _QUALITY_FLAG_NAMES[:-1]) and (
        active["quality_strategy"] == "disabled"
    )
    return bool(
        state["counts_unchanged"]
        and before == after
        and state["reviewed_effect_registry_zero"]
        and registry_zero
        and flags["quality_defaults_off"]
        and flags["quality_active_off"]
        and flags["reviewed_effects_off"]
        and flags["flags_off"]
        and quality_defaults_off
        and quality_active_off
        and not any(static_runtime.values())
    )


def _validate_metadata(
    payload: Mapping[str, Any], contract: Mapping[str, Any], expected_mode: str
) -> tuple[Mapping[str, Any], ...]:
    metadata = _rows(payload.get("fts_read_metadata"), "FTS read metadata")
    expected_ids = {
        (set_name, case_id)
        for set_name, case_ids in _mapping(contract["case_ids"], "case IDs").items()
        for case_id in case_ids
    }
    observed_ids = {(row.get("set_name"), row.get("case_id")) for row in metadata}
    if observed_ids != expected_ids or len(metadata) != len(expected_ids):
        raise ComparisonError("FTS read metadata case coverage is incomplete")
    required = {
        "requested_fts_query_mode",
        "applied_fts_query_mode",
        "fts_preparation_query_count",
        "fts_preparation_elapsed_ms",
        "bounded_or_selected_lexeme_count",
        "bounded_or_source_lexeme_count",
        "bounded_or_truncated",
        "bounded_or_empty_query",
        "bounded_or_natural_fallback_used",
        "data_query_count",
        "explain_query_count",
        "query_count",
        "reader_ms",
        "retrieval_eval_ms",
        "transaction_elapsed_ms",
    }
    for row in metadata:
        if not required <= set(row):
            raise ComparisonError("FTS read metadata fields are incomplete")
        if (
            row["requested_fts_query_mode"] != expected_mode
            or row["applied_fts_query_mode"] != expected_mode
        ):
            raise ComparisonError("requested/applied FTS mode mismatch")
        if int(row["data_query_count"]) + int(row["explain_query_count"]) != int(
            row["query_count"]
        ):
            raise ComparisonError("query-count metadata mismatch")
        if expected_mode == "NATURAL":
            if any(
                (
                    row["fts_preparation_query_count"] != 0,
                    float(row["fts_preparation_elapsed_ms"]) != 0,
                    row["bounded_or_selected_lexeme_count"] != 0,
                    row["bounded_or_source_lexeme_count"] != 0,
                    row["bounded_or_truncated"],
                    row["bounded_or_empty_query"],
                    row["bounded_or_natural_fallback_used"],
                )
            ):
                raise ComparisonError("NATURAL metadata must report zero bounded-OR shape")
        else:
            selected = int(row["bounded_or_selected_lexeme_count"])
            source = int(row["bounded_or_source_lexeme_count"])
            if (
                row["fts_preparation_query_count"] != 1
                or not 0 <= selected <= 32
                or source < selected
                or bool(row["bounded_or_truncated"]) != (source > selected)
                or bool(row["bounded_or_empty_query"]) != (source == 0)
                or row["bounded_or_natural_fallback_used"]
            ):
                raise ComparisonError("BOUNDED_OR metadata is invalid or used a fallback")
    return metadata


def _validate_report(payload: Mapping[str, Any], expected_mode: str) -> dict[str, Any]:
    _assert_content_free(payload)
    contract = _contract(payload, expected_mode)
    state = _validate_state_invariants(payload)
    metadata = _validate_metadata(payload, contract, expected_mode)
    a_rows = _rows(payload.get("set_a"), "Set A")
    b_rows = _rows(payload.get("set_b"), "Set B")
    c_rows = _rows(payload.get("set_c"), "Set C")
    citations = _rows(payload.get("citation_invariants"), "citation invariants")
    pools = _rows(payload.get("pool_measurements"), "pool measurements")
    expected_a = {(case_id, pool) for case_id in contract["case_ids"]["A"] for pool in _POOLS}
    observed_a = {(row.get("case_id"), row.get("pool_size")) for row in a_rows}
    if observed_a != expected_a or {row.get("pool_size") for row in pools} != set(_POOLS):
        raise ComparisonError("Set A or pool measurements are incomplete")
    expected_b = {(case_id, pool) for case_id in contract["case_ids"]["B"] for pool in _POOLS}
    expected_c = {(case_id, pool) for case_id in contract["case_ids"]["C"] for pool in _POOLS}
    if {(row.get("case_id"), row.get("pool_size")) for row in b_rows} != expected_b:
        raise ComparisonError("Set B is incomplete")
    if {(row.get("case_id"), row.get("pool_size")) for row in c_rows} != expected_c:
        raise ComparisonError("Set C is incomplete")
    if len(citations) != len(expected_a) + len(expected_c):
        raise ComparisonError("citation invariant coverage is incomplete")
    return {
        "contract": contract,
        "state": state,
        "metadata": metadata,
        "a_rows": a_rows,
        "b_rows": b_rows,
        "c_rows": c_rows,
        "citations": citations,
        "pools": pools,
        "set_b_summary": _mapping(payload.get("set_b_summary"), "Set B summary"),
    }


def _sum_lane(rows: Iterable[Mapping[str, Any]], field: str, lane: str) -> int:
    return sum(int(_mapping(row[field], field).get(lane, 0)) for row in rows)


def _summary(report: Mapping[str, Any], mode: str) -> dict[str, Any]:
    a_rows = tuple(row for row in report["a_rows"] if row["pool_size"] == 8)
    pool_summary = {}
    unique = {}
    for size in _POOLS:
        rows = tuple(row for row in report["a_rows"] if row["pool_size"] == size)
        candidates = sum(int(row["candidate_identity_count"]) for row in rows)
        noise = sum(int(row["nonexpected_candidate_count"]) for row in rows)
        pool_summary[str(size)] = {
            "expected_hits": sum(int(row["candidate_hits"]) for row in rows),
            "noise_count": noise,
            "noise_rate": round(noise / candidates, 6) if candidates else 0.0,
            "final_top3_expected_hits": sum(int(row["final_hits"]) for row in rows),
        }
        unique[str(size)] = {
            lane: _sum_lane(rows, "unique_expected_contribution", lane)
            for lane in ("CONTENT_FTS", "TITLE_FTS")
        }
    metadata = report["metadata"]
    return {
        "mode": mode,
        "top50": {
            "content_expected_hits": _sum_lane(a_rows, "lane_hits_at_50", "CONTENT_FTS"),
            "title_expected_hits": _sum_lane(a_rows, "lane_hits_at_50", "TITLE_FTS"),
            "content_rescue": sum(len(row["lexical_unique_rescue_numbers"]) for row in a_rows),
            "title_rescue": sum(len(row["title_unique_rescue_numbers"]) for row in a_rows),
            "fused_diagnostic_expected_hits": sum(
                int(row["fused_diagnostic_hits_at_50"]) for row in a_rows
            ),
        },
        "lane_removal_unique_expected_contribution": unique,
        "pools": pool_summary,
        "cost": {
            "data_query_count_total": sum(int(row["data_query_count"]) for row in metadata),
            "max_data_query_count": max(int(row["data_query_count"]) for row in metadata),
            "max_explain_query_count": max(int(row["explain_query_count"]) for row in metadata),
            "max_query_count": max(int(row["query_count"]) for row in metadata),
            "preparation_query_count_total": sum(
                int(row["fts_preparation_query_count"]) for row in metadata
            ),
            "preparation_total_ms": round(
                sum(float(row["fts_preparation_elapsed_ms"]) for row in metadata), 3
            ),
            "preparation_p95_ms": _percentile(
                float(row["fts_preparation_elapsed_ms"]) for row in metadata
            ),
            "reader_p95_ms": _percentile(float(row["reader_ms"]) for row in metadata),
            "retrieval_eval_p95_ms": _percentile(
                float(row["retrieval_eval_ms"]) for row in metadata
            ),
        },
        "set_b_stability": dict(report["set_b_summary"]),
        "set_c_failure_count": sum(
            len(row["invariant_failures"]) for row in report["c_rows"]
        ),
        "citation_provenance_global_counts_ok": all(
            row["resolvable"]
            and row["cleanup"] == "COMPLETED"
            and row["global_counts_match"]
            for row in report["citations"]
        ),
        "state_invariants": {
            "counts_unchanged": report["state"]["counts_unchanged"],
            "reviewed_effect_registry_zero": report["state"]["reviewed_effect_registry_zero"],
            "quality_defaults_off": report["state"]["flags"]["quality_defaults_off"],
            "quality_active_off": report["state"]["flags"]["quality_active_off"],
            "reviewed_effects_off": report["state"]["flags"]["reviewed_effects_off"],
            "runtime_imports_off": not any(
                _mapping(
                    report["state"]["flags"]["static_runtime"], "static runtime imports"
                ).values()
            ),
            "flags_off": report["state"]["flags"]["flags_off"],
            "pass": _state_invariants_pass(report["state"]),
        },
    }


def _delta(baseline: object, candidate: object) -> object:
    if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
        return {
            key: _delta(baseline[key], candidate[key])
            for key in sorted(baseline.keys() & candidate.keys())
        }
    if isinstance(baseline, (int, float)) and isinstance(candidate, (int, float)):
        return round(candidate - baseline, 6)
    return None


def compare_phase_b2a_reports(
    natural_payload: Mapping[str, Any], bounded_or_payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate paired reports and emit B2A evidence only; never approve activation."""

    natural = _validate_report(natural_payload, "NATURAL")
    bounded = _validate_report(bounded_or_payload, "BOUNDED_OR")
    comparable_fields = (
        "case_ids",
        "frozen_expected_denominator",
        "pool_sizes",
        "evaluation_source_scope",
        "semantic_model_id",
        "eligible_expected_inventory_fingerprint",
    )
    if any(natural["contract"][key] != bounded["contract"][key] for key in comparable_fields):
        raise ComparisonError("paired reports are not comparable")
    baseline, candidate = _summary(natural, "NATURAL"), _summary(bounded, "BOUNDED_OR")
    safety_ok = (
        baseline["citation_provenance_global_counts_ok"]
        and candidate["citation_provenance_global_counts_ok"]
        and baseline["set_c_failure_count"] == 0
        and candidate["set_c_failure_count"] == 0
        and baseline["state_invariants"]["pass"]
        and candidate["state_invariants"]["pass"]
    )
    max_data_query_count = max(
        baseline["cost"]["max_data_query_count"], candidate["cost"]["max_data_query_count"]
    )
    cost_ok = max_data_query_count <= 12
    mechanical_pass = safety_ok and cost_ok
    repaired = (
        candidate["top50"]["content_expected_hits"]
        > baseline["top50"]["content_expected_hits"]
        or candidate["top50"]["title_expected_hits"]
        > baseline["top50"]["title_expected_hits"]
    )
    unique = any(
        value > 0
        for pool in candidate["lane_removal_unique_expected_contribution"].values()
        for value in pool.values()
    )
    if not mechanical_pass:
        conclusion = "NO_GO_SAFETY_OR_COST"
    elif repaired and unique:
        conclusion = "POSITIVE_FTS_CONTRIBUTION"
    else:
        conclusion = "NEGATIVE_NO_UNIQUE_CONTRIBUTION"
    return {
        "report_schema_version": "PHASE-B2A-FTS-QUERY-REPAIR-1",
        "evaluation_only": True,
        "activation_approval": False,
        "comparability": {
            "same_corpus": True,
            "same_case_ids": True,
            "same_frozen_denominator": True,
            "same_pools": True,
            "same_source_scope": True,
            "same_semantic_model": True,
            "complete_mode_metadata": True,
            "complete_state_invariants": True,
        },
        "baseline": baseline,
        "candidate": candidate,
        "deltas": _delta(baseline, candidate),
        "mechanical_gate": {
            "status": "PASS_B2A_MEASURED" if mechanical_pass else "NO_GO_SAFETY_OR_COST",
            "pass": mechanical_pass,
            "both_runs_complete": True,
            "comparable": True,
            "safety_invariants_pass": safety_ok,
            "max_data_query_count": max_data_query_count,
            "data_query_limit": 12,
            "report_fields_complete": True,
        },
        "conclusion": conclusion,
        "conclusion_note": "Evaluation evidence only; this does not approve runtime activation.",
    }
