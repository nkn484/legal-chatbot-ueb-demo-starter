"""Deterministic authority-role assessment for collapsed legal candidates."""

from __future__ import annotations

from enum import StrEnum
from unicodedata import normalize
from uuid import UUID

from pydantic import Field, model_validator

from .models import CollapsedDocumentCandidate, ProvenanceType, SourceBinding, _FrozenContract


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
    source_binding_aligned: bool = False
    status_metadata_current: bool = False

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
            "source_binding_aligned": self.source_binding_aligned,
            "status_metadata_current": self.status_metadata_current,
        }


def assess_candidate_role(
    candidate: CollapsedDocumentCandidate,
    *,
    material_unit_ids: tuple[str, ...],
    unit_source_bindings: dict[str, SourceBinding],
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
    source_binding = SourceBinding(identity.source_id.value)
    aligned_units = tuple(
        unit_id
        for unit_id in supported_units
        if unit_source_bindings.get(unit_id) is source_binding
    )
    source_binding_aligned = bool(aligned_units)
    source_binding_conflicted = any(
        unit_source_bindings.get(unit_id)
        not in (SourceBinding.UNKNOWN, SourceBinding.AMBIGUOUS, source_binding)
        for unit_id in supported_units
    )
    status_metadata_current = (
        identity.legal_status is not None
        and normalize("NFC", identity.legal_status).casefold() == "còn hiệu lực"
    )
    authority_metadata_present = bool(identity.document_type and identity.issuing_authority)
    if not supported_units:
        role = AuthorityRole.IRRELEVANT
    elif manual:
        role = AuthorityRole.SUPPLEMENTARY_AUTHORITY
    elif (
        identity.provenance_type is ProvenanceType.SOURCE_FETCH
        and identity.latest_ingested
        and status_metadata_current
        and authority_metadata_present
        and not source_binding_conflicted
    ):
        role = AuthorityRole.DIRECT_AUTHORITY
    elif identity.provenance_type is ProvenanceType.SOURCE_FETCH and identity.latest_ingested:
        role = AuthorityRole.IMPLEMENTING_OR_INTERNAL_RULE
    else:
        role = AuthorityRole.BACKGROUND
    return CandidateRoleAssessment(
        document_version_id=identity.document_version_id,
        role=role,
        supported_unit_ids=supported_units,
        applicability_uncertain=True,
        manual_provenance_limited=manual,
        source_binding_aligned=source_binding_aligned,
        status_metadata_current=status_metadata_current,
    )
