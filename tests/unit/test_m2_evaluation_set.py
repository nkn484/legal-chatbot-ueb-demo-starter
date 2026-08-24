"""Unit coverage for static M2 evaluation-control artifacts only."""

from __future__ import annotations

import importlib.util
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _module():
    path = ROOT / "scripts" / "validate_m2_evaluation_set.py"
    spec = importlib.util.spec_from_file_location("m2_evaluation_set", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_m2_set_counts_and_category_distribution() -> None:
    evaluator = _module()
    manifest = ROOT / "docs/evals/m2_evaluation_set.json"
    sets = evaluator.cases_by_set(evaluator.load_evaluation_set(manifest))
    assert len(sets["B"]) == 30
    assert Counter(case["parent_case_id"] for case in sets["B"]) == {
        f"Q{number:02d}": 3 for number in range(1, 11)
    }
    assert len(sets["C"]) >= 20
    assert set(case["category"] for case in sets["C"]) == evaluator.CATEGORIES


def test_m2_set_has_no_benchmark_document_number_leakage_and_xlsx_parity() -> None:
    evaluator = _module()
    json_path = ROOT / "docs/evals/m2_evaluation_set.json"
    xlsx_path = ROOT / "docs/evals/m2_evaluation_set.xlsx"
    benchmark_path = ROOT / "docs/Stress_test_Legal_Chatbot_UEB_10_cau.xlsx"
    sets = evaluator.cases_by_set(evaluator.load_evaluation_set(json_path))
    numbers = evaluator.load_benchmark_document_numbers(benchmark_path)
    assert evaluator.find_document_number_leaks(
        (case for cases in sets.values() for case in cases), numbers
    ) == ()
    evaluator.validate_evaluation_set(json_path, xlsx_path, benchmark_path)


def test_m2_canonical_hash_is_deterministic_and_documented() -> None:
    evaluator = _module()
    json_path = ROOT / "docs/evals/m2_evaluation_set.json"
    first = evaluator.canonical_json_sha256(json_path)
    assert first == evaluator.canonical_json_sha256(json_path)
    methodology = (ROOT / "docs/evals/m2_evaluation_methodology.md").read_text(encoding="utf-8")
    documented = re.search(r"SHA-256: `([0-9a-f]{64})`", methodology)
    assert documented is not None
    assert documented.group(1) == first
