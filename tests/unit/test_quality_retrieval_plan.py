from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from scripts.validate_quality_retrieval_plan import ValidationError, validate_quality_retrieval_plan

from legal_chatbot.retrieval.config import RetrievalSettings
from legal_chatbot.retrieval.quality_repair.strategy import (
    ENVIRONMENT_FLAGS,
    QUALITY_PROFILE_NAMES,
    QUALITY_REPAIR_PROFILES,
    CandidatePoolSelectionMode,
    QualityRepairStrategy,
)


def _copy_plan_root(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[2]
    target = tmp_path / "fixture"
    source_evals = root / "docs" / "evals"
    target_evals = target / "docs" / "evals"
    target_evals.mkdir(parents=True)
    shutil.copytree(source_evals / "quality-retrieval", target_evals / "quality-retrieval")
    shutil.copy2(source_evals / "m2_evaluation_set.json", target_evals / "m2_evaluation_set.json")
    return target


def test_quality_retrieval_plan_passes_offline_freeze_checks() -> None:
    validate_quality_retrieval_plan()


def test_a1_registry_exactly_matches_the_a2_machine_contract() -> None:
    contract_path = Path("docs/evals/quality-retrieval/quality-retrieval-plan.contract.json")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    expected_names = tuple(contract["strategy_profile_contract"]["expected_profile_names"])
    assert QUALITY_PROFILE_NAMES == expected_names
    assert contract["frozen_baselines"]["prompt01_natural_exact_semantic_top50"][
        "pareto_prior_for_pool8"
    ] is True
    assert contract["environment_flags"] == [
        {"field_name": field_name, "alias": alias}
        for field_name, alias in ENVIRONMENT_FLAGS.items()
    ]
    for field_name, alias in ENVIRONMENT_FLAGS.items():
        assert RetrievalSettings.model_fields[field_name].validation_alias == alias
    hybrid = QUALITY_REPAIR_PROFILES["quality_retrieval_hybrid_v1"]
    repair = QUALITY_REPAIR_PROFILES["quality_retrieval_evidence_repair_v1"]
    full = QUALITY_REPAIR_PROFILES["quality_retrieval_full_candidate_v1"]
    assert isinstance(hybrid, QualityRepairStrategy)
    assert isinstance(repair, QualityRepairStrategy)
    assert isinstance(full, QualityRepairStrategy)
    assert hybrid.candidate_pool_selection_mode is CandidatePoolSelectionMode.PARETO_MATRIX
    assert (
        full.candidate_pool_selection_mode
        is CandidatePoolSelectionMode.POOL_SELECTED_FROM_HYBRID
    )
    assert hybrid.candidate_pool_sizes == full.candidate_pool_sizes == (8, 12, 16, 20)
    assert hybrid.capabilities["protected_opportunity_enabled"] is False
    assert full.capabilities["protected_opportunity_enabled"] is True
    assert full.capabilities["reranker_enabled"] is True
    assert repair.capabilities["reranker_enabled"] is False
    assert repair.capabilities["repair_retrieval_enabled"] is True
    c07 = contract["ablation_configurations"][6]
    c08 = contract["ablation_configurations"][7]
    assert (c07["reranker"], c07["repair"]) == ("OFF", "ONE_ROUND")
    assert (c08["reranker"], c08["repair"]) == ("ON_MAX_INPUT_20", "ONE_ROUND")
    assert c07["capabilities"]["reranker_enabled"] is not c08["capabilities"]["reranker_enabled"]
    for configuration in contract["ablation_configurations"]:
        profile = QUALITY_REPAIR_PROFILES[configuration["profile_name"]]
        if isinstance(profile, QualityRepairStrategy):
            assert dict(profile.capabilities) == configuration["capabilities"]
            assert configuration["evidence"] == {
                "minimum": profile.final_evidence_min,
                "maximum": profile.final_evidence_max,
            }


def test_quality_retrieval_plan_rejects_changed_m2_hash(tmp_path: Path) -> None:
    root = _copy_plan_root(tmp_path)
    m2_path = root / "docs" / "evals" / "m2_evaluation_set.json"
    payload = json.loads(m2_path.read_text(encoding="utf-8"))
    payload["sets"]["B"]["description"] = "changed"
    m2_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="hash"):
        validate_quality_retrieval_plan(root)


def test_quality_retrieval_plan_rejects_raw_question_field(tmp_path: Path) -> None:
    root = _copy_plan_root(tmp_path)
    path = root / "docs" / "evals" / "quality-retrieval" / "methodology.md"
    path.write_text(
        f"{path.read_text(encoding='utf-8')}\nQuestion: prohibited fixture\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="raw evaluation field"):
        validate_quality_retrieval_plan(root)


def test_quality_retrieval_plan_rejects_continuation_as_final_pass(tmp_path: Path) -> None:
    root = _copy_plan_root(tmp_path)
    path = root / "docs" / "evals" / "quality-retrieval" / "quality-retrieval-plan.contract.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["frozen_targets"]["hybrid_analyzer_continuation_final_recall_min"][
        "not_final_pass"
    ] = False
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="continuation only"):
        validate_quality_retrieval_plan(root)


def test_quality_retrieval_plan_rejects_c07_reranker_field_drift(tmp_path: Path) -> None:
    root = _copy_plan_root(tmp_path)
    path = root / "docs" / "evals" / "quality-retrieval" / "quality-retrieval-plan.contract.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["ablation_configurations"][6]["reranker"] = "ON_MAX_INPUT_20"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValidationError, match="reranker and repair fields"):
        validate_quality_retrieval_plan(root)
