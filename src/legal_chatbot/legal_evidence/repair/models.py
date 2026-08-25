"""P8 one-shot targeted repair contracts."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from legal_chatbot.legal_evidence.models import (
    AuthorityRole,
    DocumentVersionReference,
    EvidenceUnit,
)


class _FrozenRepairModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RepairOutcome(StrEnum):
    DISABLED = "DISABLED"
    EXECUTED = "EXECUTED"
    NOT_IN_CATALOG = "NOT_IN_CATALOG"
    QUARANTINED = "QUARANTINED"
    NO_TARGET = "NO_TARGET"


class RepairSettings(_FrozenRepairModel):
    enabled: bool = False


class TargetedRepairRequest(_FrozenRepairModel):
    sub_intent_id: UUID = Field(exclude=True, repr=False)
    missing_role: AuthorityRole
    documents: tuple[DocumentVersionReference, ...] = Field(
        min_length=1, max_length=30, exclude=True, repr=False
    )
    authority_roles: tuple[AuthorityRole, ...] = Field(min_length=1, max_length=30)
    query_text: str = Field(min_length=1, max_length=2000, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_document_roles(self) -> "TargetedRepairRequest":
        if len(self.documents) != len(self.authority_roles):
            raise ValueError("repair authority roles must match repair documents")
        if len({item.document_version_id for item in self.documents}) != len(self.documents):
            raise ValueError("repair documents must be unique by version")
        return self


class RepairResult(_FrozenRepairModel):
    outcome: RepairOutcome
    evidence_units: tuple[EvidenceUnit, ...] = Field(default=(), max_length=5, exclude=True)
    repair_executed: bool = False
    target_sub_intent_id: UUID | None = Field(default=None, exclude=True, repr=False)
    missing_role: AuthorityRole | None = None

    def to_public_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome.value,
            "evidence_count": len(self.evidence_units),
            "repair_executed": self.repair_executed,
            "missing_role": None if self.missing_role is None else self.missing_role.value,
        }


__all__ = ["RepairOutcome", "RepairResult", "RepairSettings", "TargetedRepairRequest"]
