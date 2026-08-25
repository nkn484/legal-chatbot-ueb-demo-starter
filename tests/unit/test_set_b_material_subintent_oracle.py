from pathlib import Path

import pytest

from legal_chatbot.diagnostics.evaluation.set_b_material_subintent import (
    SetBAnalyzerOutput,
    SetBMaterialSubintentOracleError,
    evaluate_set_b_material_subintents,
    load_set_b_material_subintent_oracle,
    load_set_b_paraphrases,
    normalize_material_sub_intents,
)

_ORACLE_PATH = Path("docs/evals/oracle/set-b-material-subintent-oracle-v1.0.0.json")
_SET_B_PATH = Path("docs/evals/m2_evaluation_set.json")


def test_oracle_is_hash_valid_and_resolves_all_thirty_set_b_paraphrases() -> None:
    oracle = load_set_b_material_subintent_oracle(_ORACLE_PATH)
    paraphrases = load_set_b_paraphrases(_SET_B_PATH, oracle)

    assert oracle.version == "1.0.0"
    assert len(oracle.gold_cases) == 10
    assert len(paraphrases) == 30
    assert {item.parent_case_id for item in paraphrases} == set(oracle.gold_cases)


def test_normalization_requires_one_canonical_id_per_output_description() -> None:
    oracle = load_set_b_material_subintent_oracle(_ORACLE_PATH)

    assert normalize_material_sub_intents(("điều kiện học vượt",), oracle) == {
        "UNDERGRAD_STUDY_AHEAD_CONDITIONS"
    }
    assert normalize_material_sub_intents(("học vượt và học lại",), oracle) is None
    assert normalize_material_sub_intents(("unmapped private phrase",), oracle) is None


def test_evaluation_requires_exact_parent_set_match_and_minimum_measurement() -> None:
    oracle = load_set_b_material_subintent_oracle(_ORACLE_PATH)
    paraphrases = load_set_b_paraphrases(_SET_B_PATH, oracle)
    outputs = tuple(
        SetBAnalyzerOutput(
            case_id=item.case_id,
            parent_case_id=item.parent_case_id,
            descriptions=("điều kiện học vượt",),
            outcome="LLM_ANALYSIS",
        )
        for item in paraphrases
    )
    measurement = evaluate_set_b_material_subintents(outputs, oracle)

    assert measurement.measured == 30
    assert measurement.matched < measurement.measured
    assert measurement.passed is False
    with pytest.raises(SetBMaterialSubintentOracleError, match="count"):
        evaluate_set_b_material_subintents(outputs[:-1], oracle)
