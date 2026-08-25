"""P6 issue-specific evidence contracts restricted to selected authority families."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.legal_evidence.models import (
    AuthorityRole,
    DocumentVersionReference,
    EvidenceReference,
    EvidenceUnit,
)


class _FrozenPinpointModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PinpointOutcome(StrEnum):
    DISABLED = "DISABLED"
    NO_ELIGIBLE_FAMILY = "NO_ELIGIBLE_FAMILY"
    COMPLETED = "COMPLETED"


class PinpointSettings(_FrozenPinpointModel):
    enabled: bool = False
    max_evidence_per_sub_intent: int = Field(default=5, ge=2, le=5)


class PinpointReadRequest(_FrozenPinpointModel):
    sub_intent_id: UUID = Field(exclude=True, repr=False)
    document_version_ids: tuple[UUID, ...] = Field(min_length=1, max_length=30, exclude=True)
    documents: tuple[DocumentVersionReference, ...] = Field(
        min_length=1, max_length=30, exclude=True, repr=False
    )
    query_text: str = Field(min_length=1, max_length=2_000, exclude=True, repr=False)

    @field_validator("document_version_ids")
    @classmethod
    def validate_versions(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("pinpoint document versions must be unique")
        return value

    @field_validator("documents")
    @classmethod
    def validate_documents(
        cls, value: tuple[DocumentVersionReference, ...]
    ) -> tuple[DocumentVersionReference, ...]:
        if len({item.document_version_id for item in value}) != len(value):
            raise ValueError("pinpoint documents must be unique by version")
        return value

    @model_validator(mode="after")
    def validate_document_identity(self) -> PinpointReadRequest:
        if self.document_version_ids != tuple(item.document_version_id for item in self.documents):
            raise ValueError("pinpoint versions must match document identities")
        return self


class RawPinpointEvidence(_FrozenPinpointModel):
    evidence: EvidenceReference = Field(exclude=True, repr=False)
    sub_intent_id: UUID = Field(exclude=True, repr=False)
    authority_role: AuthorityRole
    rank: int = Field(ge=1, le=50)


class PinpointEvidenceResult(_FrozenPinpointModel):
    evidence_units: tuple[EvidenceUnit, ...] = Field(default=(), max_length=20, exclude=True)
    outcome: PinpointOutcome

    def to_public_dict(self) -> dict[str, object]:
        by_role = {role.value: 0 for role in AuthorityRole}
        for unit in self.evidence_units:
            by_role[unit.authority_role.value] += 1
        return {
            "outcome": self.outcome.value,
            "evidence_count": len(self.evidence_units),
            "role_counts": by_role,
        }


__all__ = [
    "PinpointEvidenceResult",
    "PinpointOutcome",
    "PinpointReadRequest",
    "PinpointSettings",
    "RawPinpointEvidence",
]
