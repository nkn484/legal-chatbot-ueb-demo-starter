"""Deterministic authority-role assessment for collapsed legal candidates."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from .models import CollapsedDocumentCandidate, ProvenanceType, _FrozenContract


class AuthorityRole(StrEnum):
    """The evidence role is an internal selection aid, not a legal-effect finding."""

    DIRECT_AUTHORITY = "DIRECT_AUTHORITY"
    IMPLEMENTING_OR_INTERNAL_RULE = "IMPLEMENTING_OR_INTERNAL_RULE"
    SUPPLEMENTARY_AUTHORITY = "SUPPLEMENTARY_AUTHORITY"
    BACKGROUND = "BACKGROUND"
    IRRELEVANT = "IRRELEVANT"


class CandidateRoleAssessment(_FrozenContract):
    """Content-free role decision derived only from identity and issue alignment."""

    document_version_id: UUID = Field(exclude=True, repr=False)
    role: AuthorityRole
    supported_unit_ids: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    applicability_uncertain: bool = True
    manual_provenance_limited: bool = False

    @model_validator(mode="after")
    def validate_role_evidence(self) -> CandidateRoleAssessment:
        if len(set(self.supported_unit_ids)) != len(self.supported_unit_ids):
            raise ValueError("supported unit identifiers must be unique")
        if self.role is AuthorityRole.IRRELEVANT and self.supported_unit_ids:
            raise ValueError("irrelevant evidence cannot support a unit")
        if self.manual_provenance_limited and self.role is AuthorityRole.DIRECT_AUTHORITY:
            raise ValueError("manual provenance cannot be direct authority")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "supported_unit_count": len(self.supported_unit_ids),
            "applicability_uncertain": self.applicability_uncertain,
            "manual_provenance_limited": self.manual_provenance_limited,
        }


def assess_candidate_role(
    candidate: CollapsedDocumentCandidate,
    *,
    material_unit_ids: tuple[str, ...],
) -> CandidateRoleAssessment:
    """Classify one candidate without titles, dates, similarity, or legal-effect inference.

    A fetched, latest-ingested document that aligns with an analyzed issue is a
    direct-authority *candidate*.  Applicability remains uncertain because reviewed
    legal effects are intentionally outside this milestone.
    """

    allowed_units = set(material_unit_ids)
    supported_units = tuple(
        unit_id for unit_id in candidate.merged_unit_ids if unit_id in allowed_units
    )
    identity = candidate.identity
    manual = identity.provenance_type is ProvenanceType.MANUAL_SNAPSHOT
    if not supported_units:
        role = AuthorityRole.IRRELEVANT
    elif manual:
        role = AuthorityRole.SUPPLEMENTARY_AUTHORITY
    elif identity.provenance_type is ProvenanceType.SOURCE_FETCH and identity.latest_ingested:
        role = AuthorityRole.DIRECT_AUTHORITY
    else:
        role = AuthorityRole.BACKGROUND
    return CandidateRoleAssessment(
        document_version_id=identity.document_version_id,
        role=role,
        supported_unit_ids=supported_units,
        applicability_uncertain=True,
        manual_provenance_limited=manual,
    )
