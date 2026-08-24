from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.validate_prompt03_design_pack import ValidationError, validate_design_pack


def test_prompt03_design_pack_passes_static_documentation_checks() -> None:
    validate_design_pack()


def test_prompt03_validator_rejects_unknown_relation_kind(tmp_path: Path) -> None:
    design_dir = tmp_path / "docs" / "design"
    design_dir.mkdir(parents=True)
    source_dir = Path(__file__).resolve().parents[2] / "docs" / "design"
    for path in source_dir.iterdir():
        target = design_dir / path.name
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    source_contract = Path(__file__).resolve().parents[2] / "contracts"
    target_contract = tmp_path / "contracts"
    target_contract.mkdir()
    for path in source_contract.glob("reviewed-legal-effects-v1.schema.json"):
        (target_contract / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    schema_path = target_contract / "reviewed-legal-effects-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$defs"]["relation"]["properties"]["relation_kind"]["enum"].append("AMENDS")
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(ValidationError, match="unapproved relation kinds"):
        validate_design_pack(tmp_path)


def test_prompt03_validator_rejects_raw_evaluation_field(tmp_path: Path) -> None:
    design_dir = tmp_path / "docs" / "design"
    design_dir.mkdir(parents=True)
    source_dir = Path(__file__).resolve().parents[2] / "docs" / "design"
    for path in source_dir.iterdir():
        target = design_dir / path.name
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    source_contract = Path(__file__).resolve().parents[2] / "contracts"
    target_contract = tmp_path / "contracts"
    target_contract.mkdir()
    for path in source_contract.glob("reviewed-legal-effects-v1.schema.json"):
        (target_contract / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    inventory_path = design_dir / "prompt03-reviewed-legal-effects-inventory.md"
    inventory_path.write_text(
        f"{inventory_path.read_text(encoding='utf-8')}\nQuestion: prohibited fixture text\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="raw evaluation question or answer content"):
        validate_design_pack(tmp_path)


def test_prompt03_validator_requires_gate2_runbook_boundaries(tmp_path: Path) -> None:
    design_dir = tmp_path / "docs" / "design"
    design_dir.mkdir(parents=True)
    source_dir = Path(__file__).resolve().parents[2] / "docs" / "design"
    for path in source_dir.iterdir():
        target = design_dir / path.name
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    source_contract = Path(__file__).resolve().parents[2] / "contracts"
    target_contract = tmp_path / "contracts"
    target_contract.mkdir()
    for path in source_contract.glob("reviewed-legal-effects-v1.schema.json"):
        (target_contract / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    runbook_path = design_dir / "prompt03-gate2-importer-runbook.md"
    runbook_path.write_text(
        runbook_path.read_text(encoding="utf-8").replace(
            "Direct SQL/DML is unsupported and prohibited operationally", "unsupported writes"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="Gate-2 runbook lacks required token"):
        validate_design_pack(tmp_path)


def test_prompt03_validator_requires_gate3_closure_status(tmp_path: Path) -> None:
    design_dir = tmp_path / "docs" / "design"
    design_dir.mkdir(parents=True)
    source_dir = Path(__file__).resolve().parents[2] / "docs" / "design"
    for path in source_dir.iterdir():
        target = design_dir / path.name
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    source_contract = Path(__file__).resolve().parents[2] / "contracts"
    target_contract = tmp_path / "contracts"
    target_contract.mkdir()
    for path in source_contract.glob("reviewed-legal-effects-v1.schema.json"):
        (target_contract / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")

    runbook_path = design_dir / "prompt03-gate2-importer-runbook.md"
    runbook_path.write_text(
        runbook_path.read_text(encoding="utf-8").replace(
            "Gate-3: SYNTHETIC_SHADOW_VALIDATED", "unapproved shadow"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="Gate-2 runbook lacks required token"):
        validate_design_pack(tmp_path)
