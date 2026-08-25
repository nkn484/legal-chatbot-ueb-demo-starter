"""Structured, external-model-neutral legal evidence-pack contracts."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from legal_chatbot.retrieval.models import ResolvedCitation

from .analyzer import AnalyzerObservation
from .candidate_roles import AuthorityRole
from .coverage import EvidenceCoverageMatrix, EvidenceCoverageStatus
from .evidence_budget import EvidenceSelection
from .models import _FrozenContract


class EvidencePackLimitation(StrEnum):
    COVERAGE_GAP = "COVERAGE_GAP"
    SOURCE_ACCESS_UNAVAILABLE = "SOURCE_ACCESS_UNAVAILABLE"
    SOURCE_AMBIGUOUS = "SOURCE_AMBIGUOUS"
    APPLICABILITY_UNCERTAIN = "APPLICABILITY_UNCERTAIN"
    VERSION_UNVERIFIED = "VERSION_UNVERIFIED"
    MANUAL_PROVENANCE = "MANUAL_PROVENANCE"


class SelectedLegalAuthority(_FrozenContract):
    """One resolved citation plus its role and private excerpt for synthesis only."""

    citation: ResolvedCitation
    excerpt: str = Field(min_length=1, max_length=2_000, exclude=True, repr=False)
    role: AuthorityRole
    supported_unit_ids: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    applicability_uncertain: bool

    @model_validator(mode="after")
    def validate_authority(self) -> SelectedLegalAuthority:
        if len(set(self.supported_unit_ids)) != len(self.supported_unit_ids):
            raise ValueError("supported unit identifiers must be unique")
        return self

    @property
    def citation_id(self) -> UUID:
        return self.citation.citation_id


class StructuredEvidencePack(_FrozenContract):
    """Private request-scoped material delivered to one bounded synthesis call."""

    analysis: AnalyzerObservation = Field(exclude=True, repr=False)
    authorities: tuple[SelectedLegalAuthority, ...] = Field(min_length=1, max_length=6)
    coverage: EvidenceCoverageMatrix
    limitations: tuple[EvidencePackLimitation, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def validate_pack(self) -> StructuredEvidencePack:
        if len({authority.citation_id for authority in self.authorities}) != len(self.authorities):
            raise ValueError("authorities require unique citations")
        if len(set(self.limitations)) != len(self.limitations):
            raise ValueError("limitations must be unique")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "authority_count": len(self.authorities),
            "coverage": self.coverage.to_public_dict(),
            "limitations": [limitation.value for limitation in self.limitations],
        }


class QualityRetrievalContext(_FrozenContract):
    """Private analysis/selection state carried only from retrieval to synthesis."""

    analysis: AnalyzerObservation = Field(exclude=True, repr=False)
    selection: EvidenceSelection = Field(exclude=True, repr=False)
    coverage: EvidenceCoverageMatrix
    repair_executed: bool = False

    @model_validator(mode="after")
    def validate_context(self) -> QualityRetrievalContext:
        analysis_unit_ids = {unit.unit_id for unit in self.analysis.units}
        coverage_unit_ids = {entry.unit_id for entry in self.coverage.entries}
        if analysis_unit_ids != coverage_unit_ids:
            raise ValueError("quality coverage must exactly match analyzed units")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "selection": self.selection.to_public_dict(),
            "coverage": self.coverage.to_public_dict(),
            "repair_executed": self.repair_executed,
        }


def derive_limitations(
    coverage: EvidenceCoverageMatrix, authorities: tuple[SelectedLegalAuthority, ...]
) -> tuple[EvidencePackLimitation, ...]:
    """Expose only stable coverage limitations, never a legal-effect conclusion."""

    limitations: list[EvidencePackLimitation] = []
    statuses = {entry.status for entry in coverage.entries}
    if (
        EvidenceCoverageStatus.UNSUPPORTED in statuses
        or EvidenceCoverageStatus.PARTIALLY_SUPPORTED in statuses
    ):
        limitations.append(EvidencePackLimitation.COVERAGE_GAP)
    if EvidenceCoverageStatus.UNAVAILABLE in statuses:
        limitations.append(EvidencePackLimitation.SOURCE_ACCESS_UNAVAILABLE)
    if EvidenceCoverageStatus.AMBIGUOUS in statuses:
        limitations.append(EvidencePackLimitation.SOURCE_AMBIGUOUS)
    if any(entry.applicability_uncertain for entry in coverage.entries):
        limitations.append(EvidencePackLimitation.APPLICABILITY_UNCERTAIN)
        limitations.append(EvidencePackLimitation.VERSION_UNVERIFIED)
    if any(
        authority.citation.provenance_type.value == "manual_snapshot" for authority in authorities
    ):
        limitations.append(EvidencePackLimitation.MANUAL_PROVENANCE)
    return tuple(limitations)
