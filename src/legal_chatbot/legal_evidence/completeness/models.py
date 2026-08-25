"""P7 deterministic completeness contracts and proposal-only reviewer findings."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from legal_chatbot.legal_evidence.models import ApplicabilityState, CoverageState


class _FrozenCompletenessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MissingEvidenceCode(StrEnum):
    GOVERNING_AUTHORITY = "GOVERNING_AUTHORITY"
    IMPLEMENTING_AUTHORITY = "IMPLEMENTING_AUTHORITY"
    CLAUSE_EVIDENCE = "CLAUSE_EVIDENCE"
    APPLICABILITY = "APPLICABILITY"
    RELATION_CONFLICT = "RELATION_CONFLICT"


class CompletenessSettings(_FrozenCompletenessModel):
    enabled: bool = False
    max_output_tokens: int = Field(default=512, ge=64, le=1024)
    timeout_seconds: float = Field(default=15.0, gt=0, le=30)


class CompletenessEntry(_FrozenCompletenessModel):
    sub_intent_id: UUID = Field(exclude=True, repr=False)
    state: CoverageState
    governing_authority_present: bool
    implementing_authority_needed: bool
    implementing_authority_present: bool
    applicability: ApplicabilityState
    missing_codes: tuple[MissingEvidenceCode, ...] = ()


class CompletenessProposal(_FrozenCompletenessModel):
    sub_intent_index: int = Field(ge=0, le=3)
    missing_codes: tuple[MissingEvidenceCode, ...] = ()


class CompletenessResult(_FrozenCompletenessModel):
    entries: tuple[CompletenessEntry, ...] = Field(min_length=1, max_length=4, exclude=True)
    reviewer_used: bool = False

    def to_public_dict(self) -> dict[str, object]:
        counts = {state.value: 0 for state in CoverageState}
        for entry in self.entries:
            counts[entry.state.value] += 1
        return {"coverage_counts": counts, "reviewer_used": self.reviewer_used}


__all__ = [
    "CompletenessEntry",
    "CompletenessProposal",
    "CompletenessResult",
    "CompletenessSettings",
    "MissingEvidenceCode",
]
