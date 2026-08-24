"""Offline structural and privacy validation for the Quality Retrieval A2 plan freeze."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PLAN_DIR = Path("docs/evals/quality-retrieval")
CONTRACT_NAME = "quality-retrieval-plan.contract.json"
METRICS_SCHEMA_NAME = "quality-retrieval-metrics.schema.json"
REQUIRED_FILES = frozenset(
    {
        CONTRACT_NAME,
        METRICS_SCHEMA_NAME,
        "methodology.md",
        "ablation-matrix.md",
        "metrics-schema.md",
        "release-gates.md",
        "privacy-reviewer-protocol.md",
    }
)
M2_HASH = "41b25c2d6561f78405915241a56f654ed9dfcacecbe8a0c61c408e072fdaf6e8"
CAPABILITIES = frozenset(
    {
        "quality_repair_enabled",
        "document_collapse_enabled",
        "title_search_enabled",
        "hybrid_fusion_enabled",
        "deterministic_analyzer_enabled",
        "protected_opportunity_enabled",
        "dynamic_evidence_enabled",
        "reranker_enabled",
        "repair_retrieval_enabled",
    }
)
ENVIRONMENT_FLAGS = (
    {"field_name": "quality_repair_enabled", "alias": "RETRIEVAL_QUALITY_REPAIR_ENABLED"},
    {
        "field_name": "quality_title_search_enabled",
        "alias": "RETRIEVAL_QUALITY_TITLE_SEARCH_ENABLED",
    },
    {
        "field_name": "quality_hybrid_fusion_enabled",
        "alias": "RETRIEVAL_QUALITY_HYBRID_FUSION_ENABLED",
    },
    {
        "field_name": "quality_query_planner_enabled",
        "alias": "RETRIEVAL_QUALITY_QUERY_PLANNER_ENABLED",
    },
    {
        "field_name": "quality_dynamic_evidence_enabled",
        "alias": "RETRIEVAL_QUALITY_DYNAMIC_EVIDENCE_ENABLED",
    },
    {
        "field_name": "quality_repair_retrieval_enabled",
        "alias": "RETRIEVAL_QUALITY_REPAIR_RETRIEVAL_ENABLED",
    },
)
EXPECTED_CONFIGS = (
    ("QRRA2-C01", "Current default"),
    ("QRRA2-C02", "Document collapse only"),
    ("QRRA2-C03", "Title/FTS/Semantic hybrid"),
    ("QRRA2-C04", "Query decomposition/protected opportunity"),
    ("QRRA2-C05", "Dynamic evidence"),
    ("QRRA2-C06", "Reranker"),
    ("QRRA2-C07", "Evidence repair"),
    ("QRRA2-C08", "Full candidate configuration"),
)
URL_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
RAW_FIELD_PATTERN = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?(?:raw\s+)?(?:question|answer|chunk|query|prompt|url|uuid)\s*[:=]"
)
FORBIDDEN_MACHINE_KEYS = frozenset(
    {
        "question",
        "answer",
        "chunk",
        "content",
        "query",
        "prompt",
        "url",
        "urls",
        "uuid",
        "credential",
        "credentials",
    }
)


class ValidationError(ValueError):
    """Raised when an A2 plan artifact is missing, unsafe, or contradicts the freeze."""


def canonical_json_sha256(path: Path) -> str:
    """Hash parsed JSON independent of formatting."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError(f"{path.name} must be a JSON object")
    return payload


def _walk(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append((key, child))
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found


def _validate_privacy(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if URL_PATTERN.search(text):
        raise ValidationError(f"{path.name} contains a URL")
    if UUID_PATTERN.search(text):
        raise ValidationError(f"{path.name} contains a UUID")
    if path.suffix == ".md" and RAW_FIELD_PATTERN.search(text):
        raise ValidationError(f"{path.name} contains a raw evaluation field")
    if path.suffix == ".json":
        for key, value in _walk(_read_json(path)):
            if key.casefold() in FORBIDDEN_MACHINE_KEYS:
                raise ValidationError(f"{path.name} exposes prohibited raw field: {key}")
            if isinstance(value, str) and (URL_PATTERN.search(value) or UUID_PATTERN.search(value)):
                raise ValidationError(f"{path.name} contains prohibited raw locator content")


def _require_ratio(payload: object, expected: tuple[int, int], name: str) -> None:
    if not isinstance(payload, dict) or (
        payload.get("numerator"),
        payload.get("denominator"),
    ) != expected:
        raise ValidationError(f"{name} must be {expected[0]}/{expected[1]}")


def _validate_m2(root: Path, contract: dict[str, Any]) -> None:
    m2_path = root / "docs/evals/m2_evaluation_set.json"
    if not m2_path.is_file():
        raise ValidationError("frozen M2 evaluation set is missing")
    if canonical_json_sha256(m2_path) != M2_HASH:
        raise ValidationError("frozen M2 evaluation-set hash does not match")
    payload = _read_json(m2_path)
    sets = payload.get("sets")
    if not isinstance(sets, dict):
        raise ValidationError("frozen M2 evaluation set has no sets")
    try:
        set_b = sets["B"]["cases"]
        set_c = sets["C"]["cases"]
    except (KeyError, TypeError) as error:
        raise ValidationError("frozen M2 evaluation set has invalid case arrays") from error
    distribution = dict(sorted(Counter(case["category"] for case in set_c).items()))
    frozen = contract.get("frozen_inventory", {}).get("m2_control_set", {})
    if (len(set_b), len(set_c)) != (30, 24):
        raise ValidationError("frozen M2 counts must be B=30 and C=24")
    if (
        frozen.get("canonical_json_sha256") != M2_HASH
        or frozen.get("set_b_count") != 30
        or frozen.get("set_c_count") != 24
    ):
        raise ValidationError("contract does not pin frozen M2 hash and counts")
    if frozen.get("set_c_category_distribution") != distribution:
        raise ValidationError("contract M2 category distribution does not match")


def _validate_contract(contract: dict[str, Any]) -> None:
    if contract.get("contract_version") != "QUALITY-RETRIEVAL-A2-PLAN-1":
        raise ValidationError("unexpected plan contract version")
    inventory = contract.get("frozen_inventory", {})
    if inventory.get("quality_expected_identity_case_occurrences") != 29:
        raise ValidationError("quality denominator must be 29 case-occurrences")
    if "26" not in str(inventory.get("old_report_denominator_explanation", "")):
        raise ValidationError("contract must explain the old 26 versus 29 denominator")
    baselines = contract.get("frozen_baselines", {})
    if baselines.get("current_default_lexical_safe_control", {}).get("result") != "NO_RESULTS":
        raise ValidationError("current default must remain NO_RESULTS safety control")
    _require_ratio(
        baselines.get("prompt01_natural_exact_semantic_top50", {}).get(
            "expected_identity_availability"
        ),
        (24, 29),
        "natural semantic top50",
    )
    if baselines.get("prompt01_natural_exact_semantic_top50", {}).get(
        "pareto_prior_for_pool8"
    ) is not True:
        raise ValidationError("natural semantic top50 must be the frozen Pareto prior for pool 8")
    _require_ratio(
        baselines.get("prompt01_production_equivalent_final_top3", {}).get(
            "expected_identity_availability"
        ),
        (6, 29),
        "production final top3",
    )
    _require_ratio(
        baselines.get("phase4_semantic_rerank_final", {}).get(
            "expected_identity_availability"
        ),
        (8, 29),
        "Phase4 semantic-rerank",
    )
    m2 = baselines.get("m2_metadata_repair_negative_evidence", {})
    if m2.get("expected_identity_availability_before_after") != {
        "before": 8,
        "after": 8,
        "denominator": 29,
    }:
        raise ValidationError("M2 negative comparator must remain 8/29 to 8/29")
    if "cannot" not in str(m2.get("rule", "")).casefold():
        raise ValidationError("M2 negative comparator must be ineligible to win")
    if set(contract.get("capabilities", [])) != CAPABILITIES:
        raise ValidationError("strategy capability names are incomplete or changed")
    if contract.get("environment_flags") != list(ENVIRONMENT_FLAGS):
        raise ValidationError("six environment flags are incomplete or changed")
    configs = contract.get("ablation_configurations")
    config_ids_and_names = [
        (item.get("stable_id"), item.get("name")) for item in configs
    ] if isinstance(configs, list) else []
    if not isinstance(configs, list) or config_ids_and_names != list(EXPECTED_CONFIGS):
        raise ValidationError("eight frozen ablation configurations are missing or reordered")
    names = contract.get("strategy_profile_contract", {}).get("expected_profile_names")
    profiles = [item.get("profile_name") for item in configs]
    if names != profiles or len(set(profiles)) != 8:
        raise ValidationError("A1/A2 profile-name contract does not exactly match configurations")
    for item in configs:
        if item.get("version") != "1" or set(item.get("capabilities", {})) != CAPABILITIES:
            raise ValidationError("each configuration requires version and every frozen capability")
        pool = item.get("candidate_pool", {})
        evidence = item.get("evidence", {})
        if (
            not pool.get("sizes")
            or not {"minimum", "maximum"} <= set(evidence)
            or "reranker" not in item
            or "repair" not in item
        ):
            raise ValidationError(
                "each configuration requires pool, evidence, reranker, and repair settings"
            )
    c03 = configs[2]
    if (
        c03.get("candidate_pool", {}).get("sizes") != [8, 12, 16, 20]
        or c03.get("candidate_pool", {}).get("subrows")
        != ["QRRA2-C03-P08", "QRRA2-C03-P12", "QRRA2-C03-P16", "QRRA2-C03-P20"]
    ):
        raise ValidationError("hybrid pool matrix/subrows must be frozen at 8/12/16/20")
    for item in configs[1:]:
        capabilities = item["capabilities"]
        expected_evidence_max = 6 if capabilities["dynamic_evidence_enabled"] else 3
        if item["evidence"] != {"minimum": 3, "maximum": expected_evidence_max}:
            raise ValidationError("dynamic evidence must determine the frozen 3/3 or 3/6 bounds")
    c07_configuration = configs[6]
    c08_configuration = configs[7]
    c07 = c07_configuration["capabilities"]
    c08 = c08_configuration["capabilities"]
    if c07["reranker_enabled"] or not c07["repair_retrieval_enabled"]:
        raise ValidationError("C07 must isolate one-shot repair without reranking")
    if not (c08["reranker_enabled"] and c08["repair_retrieval_enabled"]):
        raise ValidationError("C08 must combine reranking and one-shot repair")
    if c07["reranker_enabled"] == c08["reranker_enabled"]:
        raise ValidationError("C07 and C08 must differ in reranker capability")
    if (
        c07_configuration["reranker"] != "OFF"
        or c07_configuration["repair"] != "ONE_ROUND"
        or c08_configuration["reranker"] != "ON_MAX_INPUT_20"
        or c08_configuration["repair"] != "ONE_ROUND"
    ):
        raise ValidationError("C07/C08 reranker and repair fields must remain distinct")
    controls = contract.get("nonrelease_controls", [])
    if len(controls) != 3 or any(item.get("release_eligible") is not False for item in controls):
        raise ValidationError("semantic and M2 references must be nonrelease controls")
    budgets = contract.get("frozen_budgets", {})
    if (
        budgets.get("candidate_pool_matrix") != [8, 12, 16, 20]
        or budgets.get("reranker_input_max") != 20
        or budgets.get("retrieval_end_to_end_p95_ms_max") != 2450
        or budgets.get("logical_db_query_count_per_case_max") != 12
        or budgets.get("repair_rounds_max") != 1
    ):
        raise ValidationError("pool, reranker, latency, query-count, or repair budget changed")
    targets = contract.get("frozen_targets", {})
    _require_ratio(targets.get("broad_expected_recall_min"), (27, 29), "broad target")
    continuation = targets.get("hybrid_analyzer_continuation_final_recall_min", {})
    _require_ratio(continuation, (12, 29), "continuation target")
    if continuation.get("not_final_pass") is not True:
        raise ValidationError("12/29 must be marked as continuation only")
    _require_ratio(targets.get("final_expected_recall_min"), (20, 29), "final target")
    _require_ratio(targets.get("false_insufficiency_max"), (0, 10), "false-insufficiency target")
    if (
        targets.get("reviewed_legal_effects") != "OFF"
        or targets.get("production_auto_enable") is not False
    ):
        raise ValidationError("Reviewed Legal Effects must remain OFF with no auto-enable")


def _validate_metrics_schema(schema: dict[str, Any]) -> None:
    if schema.get("title") != "Quality Retrieval A2 Measurement Record":
        raise ValidationError("metrics schema title is invalid")
    defs = schema.get("$defs", {})
    aggregate = defs.get("aggregateMetrics", {}).get("required", [])
    case = defs.get("caseMetrics", {}).get("required", [])
    required = {
        "expected_recall_at_8",
        "expected_recall_at_20",
        "expected_recall_at_50",
        "final_expected_recall",
        "direct_title_hit",
        "lexical_expected_hit",
        "semantic_expected_hit",
        "source_coverage",
        "sub_intent_coverage",
        "wrong_doc_rate",
        "false_insufficient",
        "reranker_promoted_expected",
        "reranker_demoted_expected",
        "reranker_promoted_wrong",
        "reranker_demoted_wrong",
        "db_cost",
        "answer_grounded",
        "evidence_count",
        "candidate_to_final_loss",
        "invariant_failures",
    }
    if not required <= set(aggregate) or not required <= set(case):
        raise ValidationError("metrics schema lacks required aggregate/per-case metrics")
    if not {"latency_p50_ms", "latency_p95_ms"} <= set(aggregate) or "latency_ms" not in case:
        raise ValidationError("metrics schema lacks latency metrics")
    db_required = defs.get("dbCost", {}).get("required", [])
    if set(db_required) != {
        "query_count",
        "lane_ms",
        "transaction_ms",
        "rows",
        "buffer_hits",
        "buffer_reads",
    }:
        raise ValidationError("metrics schema DB cost fields changed")
    repair = defs.get("caseMetrics", {}).get("properties", {}).get("repair_trace", {})
    if repair.get("additionalProperties") is not False:
        raise ValidationError("repair trace must prohibit raw query fields")


def _validate_markdown(plan_dir: Path) -> None:
    required_tokens = {
        "methodology.md": (
            "Pareto eligible",
            "29 retrievable expected identity case-occurrences",
            "Reviewed Legal Effects` remains **OFF**",
            "no legacy LLM planner/provider call",
            "no model-based query rewrite",
            "Observation source scope is derived strictly from authoritative unit scopes",
            "Pool 8 compares to the frozen natural exact semantic top50 reference",
            "Diagnostic fused top50 is recall measurement only",
        ),
        "ablation-matrix.md": ("QRRA2-C03-P08", "cannot win", "A1 reconciliation boundary"),
        "metrics-schema.md": ("Expected recall@8/@20/@50", "Set B only", "Set C only"),
        "release-gates.md": (
            "≥27/29",
            "≥20/29",
            "**not** final PASS",
            "future blinded confirmation set",
        ),
        "privacy-reviewer-protocol.md": (
            "4/10",
            "5.49/10",
            "raw questions, answers, chunks, queries, prompts",
            "after the final configuration is frozen",
        ),
    }
    for name, tokens in required_tokens.items():
        text = (plan_dir / name).read_text(encoding="utf-8")
        missing = [token for token in tokens if token not in text]
        if missing:
            raise ValidationError(f"{name} lacks frozen token(s): {', '.join(missing)}")


def validate_quality_retrieval_plan(root: Path = ROOT) -> None:
    """Validate plan-only artifacts without network, runtime, database, or model access."""

    plan_dir = root / PLAN_DIR
    missing = sorted(name for name in REQUIRED_FILES if not (plan_dir / name).is_file())
    if missing:
        raise ValidationError(
            f"missing required quality-retrieval plan files: {', '.join(missing)}"
        )
    for name in REQUIRED_FILES:
        _validate_privacy(plan_dir / name)
    contract = _read_json(plan_dir / CONTRACT_NAME)
    _validate_contract(contract)
    _validate_m2(root, contract)
    _validate_metrics_schema(_read_json(plan_dir / METRICS_SCHEMA_NAME))
    _validate_markdown(plan_dir)


def main() -> int:
    try:
        validate_quality_retrieval_plan()
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        print(f"quality retrieval plan validation failed: {error}", file=sys.stderr)
        return 1
    print("quality retrieval plan validation passed (offline plan-only checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
