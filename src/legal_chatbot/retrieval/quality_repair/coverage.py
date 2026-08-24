"""Evidence completeness classification before legal-answer synthesis."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from .analyzer import AnalyzerObservation, AnalyzerUnit
from .candidate_roles import AuthorityRole
from .evidence_budget import EvidenceSelection
from .models import SourceBinding, SourceId, _FrozenContract


class EvidenceCoverageStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceCoverageEntry(_FrozenContract):
    """One private unit binding and its content-free evidence state."""

    unit_id: str = Field(exclude=True, repr=False)
    status: EvidenceCoverageStatus
    direct_authority_present: bool
    source_scope_appropriate: bool
    applicability_uncertain: bool
    conflicting_evidence: bool = False

    def to_public_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "direct_authority_present": self.direct_authority_present,
            "source_scope_appropriate": self.source_scope_appropriate,
            "applicability_uncertain": self.applicability_uncertain,
            "conflicting_evidence": self.conflicting_evidence,
        }


class EvidenceCoverageMatrix(_FrozenContract):
    entries: tuple[EvidenceCoverageEntry, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_entries(self) -> EvidenceCoverageMatrix:
        if len({entry.unit_id for entry in self.entries}) != len(self.entries):
            raise ValueError("coverage entries must be unique per unit")
        return self

    @property
    def has_material_gap(self) -> bool:
        return any(
            entry.status
            in (EvidenceCoverageStatus.PARTIALLY_SUPPORTED, EvidenceCoverageStatus.UNSUPPORTED)
            for entry in self.entries
        )

    @property
    def unresolved_unit_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.unit_id
            for entry in self.entries
            if entry.status
            in (EvidenceCoverageStatus.PARTIALLY_SUPPORTED, EvidenceCoverageStatus.UNSUPPORTED)
        )

    def to_public_dict(self) -> dict[str, object]:
        counts = {status.value: 0 for status in EvidenceCoverageStatus}
        for entry in self.entries:
            counts[entry.status.value] += 1
        return {"status_counts": counts, "has_material_gap": self.has_material_gap}


def _source_available(unit: AnalyzerUnit, active_source_ids: tuple[SourceId, ...]) -> bool:
    if unit.source_binding in (SourceBinding.UNKNOWN, SourceBinding.AMBIGUOUS):
        return True
    return SourceId(unit.source_binding.value) in active_source_ids


def build_coverage_matrix(
    analysis: AnalyzerObservation,
    selection: EvidenceSelection,
    *,
    active_source_ids: tuple[SourceId, ...],
) -> EvidenceCoverageMatrix:
    """Classify every analyzed unit without treating planned-source absence as evidence."""

    active = tuple(dict.fromkeys(active_source_ids))
    if not active:
        raise ValueError("active source scope is required")
    entries: list[EvidenceCoverageEntry] = []
    for unit in analysis.units:
        supporting = tuple(
            assessment
            for assessment in selection.assessments
            if unit.unit_id in assessment.supported_unit_ids
        )
        direct = any(item.role is AuthorityRole.DIRECT_AUTHORITY for item in supporting)
        source_available = _source_available(unit, active)
        if unit.source_binding is SourceBinding.AMBIGUOUS:
            status = EvidenceCoverageStatus.AMBIGUOUS
        elif not source_available and not supporting:
            status = EvidenceCoverageStatus.UNAVAILABLE
        elif not supporting:
            status = EvidenceCoverageStatus.UNSUPPORTED
        elif direct:
            status = EvidenceCoverageStatus.SUPPORTED
        else:
            status = EvidenceCoverageStatus.PARTIALLY_SUPPORTED
        entries.append(
            EvidenceCoverageEntry(
                unit_id=unit.unit_id,
                status=status,
                direct_authority_present=direct,
                source_scope_appropriate=source_available,
                applicability_uncertain=any(item.applicability_uncertain for item in supporting),
            )
        )
    return EvidenceCoverageMatrix(entries=tuple(entries))
