"""One bounded, memory-only retrieval-repair plan for an unresolved issue."""

from __future__ import annotations

from pydantic import Field

from .analyzer import AnalyzerObservation, AnalyzerUnit
from .coverage import EvidenceCoverageMatrix
from .models import _FrozenContract

_MAX_REPAIR_TERMS = 8


class TargetedRepairPlan(_FrozenContract):
    """A single query derived from an already-recorded coverage gap."""

    unit_id: str = Field(exclude=True, repr=False)
    query_text: str = Field(exclude=True, repr=False, min_length=1, max_length=1_024)

    def to_public_dict(self) -> dict[str, object]:
        return {"repair_planned": True}


def _repair_terms(unit: AnalyzerUnit) -> tuple[str, ...]:
    concepts = unit.concept_query
    values = (
        *concepts.document_number_tokens,
        *concepts.important_noun_phrases,
        *concepts.safe_aliases,
        *concepts.core_concepts,
    )
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
        if len(unique) == _MAX_REPAIR_TERMS:
            break
    return tuple(unique)


def plan_targeted_repair(
    analysis: AnalyzerObservation, coverage: EvidenceCoverageMatrix
) -> TargetedRepairPlan | None:
    """Return at most one repair request; unavailable and ambiguous scopes do not retry."""

    unresolved = set(coverage.unresolved_unit_ids)
    unit = next((item for item in analysis.units if item.unit_id in unresolved), None)
    if unit is None:
        return None
    terms = _repair_terms(unit)
    if not terms:
        return None
    return TargetedRepairPlan(unit_id=unit.unit_id, query_text=" ".join(terms))
