"""P10 structured evidence-pack and answer-claim contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from legal_chatbot.legal_evidence.models import EvidenceUnit


class _FrozenCompositionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimKind(StrEnum):
    SOURCE_FACT = "SOURCE_FACT"
    SUPPORTED_INTERPRETATION = "SUPPORTED_INTERPRETATION"
    LIMITATION = "LIMITATION"
    NEXT_CHECK = "NEXT_CHECK"


class CompositionSettings(_FrozenCompositionModel):
    enabled: bool = False
    max_output_tokens: int = Field(default=768, ge=64, le=1024)
    timeout_seconds: float = Field(default=20.0, gt=0, le=30)


class CompositionEvidence(_FrozenCompositionModel):
    unit: EvidenceUnit = Field(exclude=True, repr=False)
    excerpt: str = Field(min_length=1, max_length=8000, exclude=True, repr=False)


class AnswerClaim(_FrozenCompositionModel):
    claim_index: int = Field(ge=0, le=50)
    kind: ClaimKind
    sub_intent_indices: tuple[int, ...] = Field(default=(), max_length=4)
    evidence_indices: tuple[int, ...] = Field(default=(), max_length=6)


class CompositionResult(_FrozenCompositionModel):
    answer: str | None = Field(default=None, max_length=20000, exclude=True, repr=False)
    claims: tuple[AnswerClaim, ...] = Field(default=(), max_length=50)
    enabled: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "claim_count": len(self.claims),
            "has_answer": self.answer is not None,
        }


__all__ = [
    "AnswerClaim",
    "ClaimKind",
    "CompositionEvidence",
    "CompositionResult",
    "CompositionSettings",
]
