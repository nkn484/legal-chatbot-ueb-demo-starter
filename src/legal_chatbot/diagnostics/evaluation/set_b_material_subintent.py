"""Evaluation-only Set B material-sub-intent oracle handling.

This module is intentionally outside production runtime composition. It loads
reviewer-provided evaluation data only when an evaluation caller supplies paths.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

NORMALIZER_VERSION = "set-b-material-subintent-normalizer-v1"


class SetBMaterialSubintentOracleError(ValueError):
    """Raised for malformed, tampered, or incomplete evaluator-only artifacts."""


@dataclass(frozen=True)
class SetBGoldCase:
    case_id: str
    material_sub_intents: frozenset[str]


@dataclass(frozen=True)
class SetBMaterialSubintentOracle:
    version: str
    canonical_sha256: str
    expected_paraphrases: int
    threshold: float
    minimum_measured_paraphrases: int
    gold_cases: dict[str, SetBGoldCase]
    aliases_by_id: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class SetBParaphraseCase:
    case_id: str
    parent_case_id: str
    question: str = field(repr=False)


@dataclass(frozen=True)
class SetBAnalyzerOutput:
    case_id: str
    parent_case_id: str
    descriptions: tuple[str, ...]
    outcome: str


@dataclass(frozen=True)
class SetBCaseMeasurement:
    case_id: str
    parent_case_id: str
    exact_match: bool
    outcome: str


@dataclass(frozen=True)
class SetBMaterialSubintentMeasurement:
    measured: int
    matched: int
    agreement: float
    minimum_measured_paraphrases: int
    threshold: float
    cases: tuple[SetBCaseMeasurement, ...]

    @property
    def passed(self) -> bool:
        return (
            self.measured >= self.minimum_measured_paraphrases and self.agreement >= self.threshold
        )

    def to_public_dict(self) -> dict[str, object]:
        """Return safe evaluation metadata without questions or analyzer text."""

        return {
            "measured": self.measured,
            "matched": self.matched,
            "agreement": self.agreement,
            "minimum_measured_paraphrases": self.minimum_measured_paraphrases,
            "threshold": self.threshold,
            "passed": self.passed,
            "cases": [
                {
                    "case_id": item.case_id,
                    "parent_case_id": item.parent_case_id,
                    "exact_match": item.exact_match,
                    "outcome": item.outcome,
                }
                for item in self.cases
            ],
        }


def _normalized(value: str) -> str:
    if not isinstance(value, str):
        raise SetBMaterialSubintentOracleError("oracle text must be a string")
    normalized = " ".join(unicodedata.normalize("NFC", value).casefold().split())
    if not normalized:
        raise SetBMaterialSubintentOracleError("oracle text must be nonblank")
    return normalized


def _canonical_sha256(raw: dict[str, object]) -> str:
    canonical = dict(raw)
    canonical.pop("canonical_sha256", None)
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def load_set_b_material_subintent_oracle(path: Path) -> SetBMaterialSubintentOracle:
    """Load and hash-verify the reviewer oracle without exposing it to production code."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError
        expected_hash = raw.get("canonical_sha256")
        if not isinstance(expected_hash, str) or _canonical_sha256(raw) != expected_hash:
            raise ValueError
        scope = raw["scope"]
        gate = raw["gate"]
        normalization = raw["normalization"]
        cases = raw["cases"]
        if not all(isinstance(item, dict) for item in (scope, gate, normalization)):
            raise ValueError
        if not isinstance(cases, list):
            raise ValueError
        expected_paraphrases = scope["set_b_expected_paraphrases"]
        maximum_sub_intents = scope["max_material_sub_intents_per_case"]
        threshold = gate["threshold"]
        minimum = gate["minimum_measured_paraphrases"]
        taxonomy = normalization["taxonomy"]
        if (
            not isinstance(expected_paraphrases, int)
            or not isinstance(maximum_sub_intents, int)
            or not isinstance(threshold, (int, float))
            or not isinstance(minimum, int)
            or not isinstance(taxonomy, list)
        ):
            raise ValueError
        gold_cases: dict[str, SetBGoldCase] = {}
        for item in cases:
            if not isinstance(item, dict):
                raise ValueError
            case_id = _normalized(item["case_id"]).upper()
            intent_values = item["material_sub_intents"]
            if not isinstance(intent_values, list) or not (
                1 <= len(intent_values) <= maximum_sub_intents
            ):
                raise ValueError
            gold = frozenset(_normalized(value).upper() for value in intent_values)
            if len(gold) != len(intent_values) or case_id in gold_cases:
                raise ValueError
            gold_cases[case_id] = SetBGoldCase(case_id=case_id, material_sub_intents=gold)
        aliases_by_id: dict[str, tuple[str, ...]] = {}
        for item in taxonomy:
            if not isinstance(item, dict) or not isinstance(item.get("aliases"), list):
                raise ValueError
            identifier = _normalized(item["id"]).upper()
            aliases = tuple(_normalized(value) for value in item["aliases"])
            if not aliases or len(set(aliases)) != len(aliases) or identifier in aliases_by_id:
                raise ValueError
            aliases_by_id[identifier] = aliases
        if set().union(*(case.material_sub_intents for case in gold_cases.values())) - set(
            aliases_by_id
        ):
            raise ValueError
        return SetBMaterialSubintentOracle(
            version=_normalized(raw["oracle_version"]),
            canonical_sha256=expected_hash,
            expected_paraphrases=expected_paraphrases,
            threshold=float(threshold),
            minimum_measured_paraphrases=minimum,
            gold_cases=gold_cases,
            aliases_by_id=aliases_by_id,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SetBMaterialSubintentOracleError(
            "Set B material-sub-intent oracle is invalid"
        ) from error


def load_set_b_paraphrases(
    path: Path, oracle: SetBMaterialSubintentOracle
) -> tuple[SetBParaphraseCase, ...]:
    """Load exactly the oracle's expected Set B inputs for an evaluation run."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        cases = raw["sets"]["B"]["cases"]
        if not isinstance(cases, list) or len(cases) != oracle.expected_paraphrases:
            raise ValueError
        loaded: list[SetBParaphraseCase] = []
        identifiers: set[str] = set()
        for item in cases:
            if not isinstance(item, dict):
                raise ValueError
            case_id = _normalized(item["case_id"]).upper()
            parent_case_id = _normalized(item["parent_case_id"]).upper()
            question = _normalized(item["question"])
            if case_id in identifiers or parent_case_id not in oracle.gold_cases:
                raise ValueError
            identifiers.add(case_id)
            loaded.append(
                SetBParaphraseCase(
                    case_id=case_id,
                    parent_case_id=parent_case_id,
                    question=question,
                )
            )
        return tuple(loaded)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise SetBMaterialSubintentOracleError("Set B paraphrase artifact is invalid") from error


def normalize_material_sub_intents(
    descriptions: tuple[str, ...], oracle: SetBMaterialSubintentOracle
) -> frozenset[str] | None:
    """Map each output description to exactly one evaluator-only canonical identifier."""

    normalized_ids: set[str] = set()
    for description in descriptions:
        normalized_description = _normalized(description)
        matched_ids = {
            identifier
            for identifier, aliases in oracle.aliases_by_id.items()
            if any(alias in normalized_description for alias in aliases)
        }
        if len(matched_ids) != 1:
            return None
        normalized_ids.update(matched_ids)
    return frozenset(normalized_ids)


def evaluate_set_b_material_subintents(
    outputs: tuple[SetBAnalyzerOutput, ...], oracle: SetBMaterialSubintentOracle
) -> SetBMaterialSubintentMeasurement:
    """Apply the frozen exact-set rule without inspecting questions in public output."""

    if len(outputs) != oracle.expected_paraphrases:
        raise SetBMaterialSubintentOracleError("Set B output count does not match the oracle")
    seen: set[str] = set()
    measurements: list[SetBCaseMeasurement] = []
    for output in outputs:
        if output.case_id in seen or output.parent_case_id not in oracle.gold_cases:
            raise SetBMaterialSubintentOracleError("Set B output identity is invalid")
        seen.add(output.case_id)
        normalized = normalize_material_sub_intents(output.descriptions, oracle)
        exact_match = normalized == oracle.gold_cases[output.parent_case_id].material_sub_intents
        measurements.append(
            SetBCaseMeasurement(
                case_id=output.case_id,
                parent_case_id=output.parent_case_id,
                exact_match=exact_match,
                outcome=_normalized(output.outcome).upper(),
            )
        )
    matched = sum(item.exact_match for item in measurements)
    measured = len(measurements)
    return SetBMaterialSubintentMeasurement(
        measured=measured,
        matched=matched,
        agreement=matched / measured,
        minimum_measured_paraphrases=oracle.minimum_measured_paraphrases,
        threshold=oracle.threshold,
        cases=tuple(measurements),
    )


__all__ = [
    "NORMALIZER_VERSION",
    "SetBAnalyzerOutput",
    "SetBMaterialSubintentMeasurement",
    "SetBMaterialSubintentOracle",
    "SetBMaterialSubintentOracleError",
    "SetBParaphraseCase",
    "evaluate_set_b_material_subintents",
    "load_set_b_material_subintent_oracle",
    "load_set_b_paraphrases",
    "normalize_material_sub_intents",
]
