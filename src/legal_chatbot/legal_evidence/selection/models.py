"""P9 coverage-first final evidence selection contracts."""

from pydantic import BaseModel, ConfigDict, Field

from legal_chatbot.legal_evidence.models import EvidenceUnit


class _FrozenSelectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSelectionSettings(_FrozenSelectionModel):
    enabled: bool = False
    max_evidence: int = Field(default=6, ge=3, le=6)


class FinalEvidenceSelection(_FrozenSelectionModel):
    evidence_units: tuple[EvidenceUnit, ...] = Field(default=(), max_length=6, exclude=True)
    selection_reasons: tuple[str, ...] = Field(default=(), max_length=6)
    target_count: int = Field(ge=3, le=6)
    padding_used: bool = False

    def to_public_dict(self) -> dict[str, object]:
        return {
            "selected_count": len(self.evidence_units),
            "target_count": self.target_count,
            "padding_used": self.padding_used,
            "selection_reason_count": len(self.selection_reasons),
        }


__all__ = ["EvidenceSelectionSettings", "FinalEvidenceSelection"]
