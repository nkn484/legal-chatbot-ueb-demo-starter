"""Deterministic structural claim-to-evidence validation without model review."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from .evidence_pack import StructuredEvidencePack
from .models import _FrozenContract


class ClaimValidationStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_QUALIFICATION = "SUPPORTED_WITH_QUALIFICATION"
    UNSUPPORTED = "UNSUPPORTED"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class MaterialClaim(_FrozenContract):
    """Opaque material claim metadata supplied by a trusted synthesis boundary."""

    claim_id: str = Field(min_length=1, max_length=64)
    unit_ids: tuple[str, ...] = Field(min_length=1, max_length=4, exclude=True, repr=False)
    citation_ids: tuple[UUID, ...] = Field(default=(), max_length=6, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_claim(self) -> MaterialClaim:
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ValueError("claim units must be unique")
        if len(set(self.citation_ids)) != len(self.citation_ids):
            raise ValueError("claim citations must be unique")
        return self


class ClaimValidation(_FrozenContract):
    claim_id: str = Field(min_length=1, max_length=64)
    status: ClaimValidationStatus


class ClaimValidationResult(_FrozenContract):
    claims: tuple[ClaimValidation, ...]

    @model_validator(mode="after")
    def validate_claims(self) -> ClaimValidationResult:
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim validations must be unique")
        return self

    @property
    def has_material_unsupported_claim(self) -> bool:
        return any(claim.status is ClaimValidationStatus.UNSUPPORTED for claim in self.claims)


def validate_material_claims(
    claims: tuple[MaterialClaim, ...], pack: StructuredEvidencePack
) -> ClaimValidationResult:
    """Validate citation ownership and unit coverage, never factual legal reasoning."""

    authority_by_citation = {authority.citation_id: authority for authority in pack.authorities}
    coverage_by_unit = {entry.unit_id: entry for entry in pack.coverage.entries}
    outcomes: list[ClaimValidation] = []
    for claim in claims:
        units = tuple(coverage_by_unit.get(unit_id) for unit_id in claim.unit_ids)
        cited = tuple(authority_by_citation.get(citation_id) for citation_id in claim.citation_ids)
        if any(item is None for item in units) or any(item is None for item in cited):
            status = ClaimValidationStatus.UNSUPPORTED
        elif any(
            item.status.value in ("UNSUPPORTED", "UNAVAILABLE")
            for item in units
            if item is not None
        ):
            status = ClaimValidationStatus.INSUFFICIENT_CONTEXT
        elif not cited:
            status = ClaimValidationStatus.UNSUPPORTED
        elif any(item.conflicting_evidence for item in units if item is not None):
            status = ClaimValidationStatus.EVIDENCE_CONFLICT
        elif any(item.applicability_uncertain for item in units if item is not None):
            status = ClaimValidationStatus.SUPPORTED_WITH_QUALIFICATION
        else:
            status = ClaimValidationStatus.SUPPORTED
        outcomes.append(ClaimValidation(claim_id=claim.claim_id, status=status))
    return ClaimValidationResult(claims=tuple(outcomes))
