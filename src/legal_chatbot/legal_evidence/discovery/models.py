"""Pure, provenance-preserving contracts for P3 broad document discovery."""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.legal_evidence.models import AuthorityState, DocumentVersionReference

_MAX_WORKSPACE = 30
_MAX_SUB_INTENTS = 4


class _FrozenDiscoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DiscoveryLane(StrEnum):
    TITLE_METADATA = "TITLE_METADATA"
    CONTENT_FTS = "CONTENT_FTS"
    SEMANTIC_VECTOR = "SEMANTIC_VECTOR"


class DiscoveryOutcome(StrEnum):
    DISABLED = "DISABLED"
    COMPLETED = "COMPLETED"


class DiscoverySettings(_FrozenDiscoveryModel):
    """Default-off P3 settings with a bounded investigation workspace."""

    enabled: bool = False
    workspace_limit: int = Field(default=_MAX_WORKSPACE, ge=15, le=_MAX_WORKSPACE)


class DiscoveryLaneObservation(_FrozenDiscoveryModel):
    lane: DiscoveryLane
    rank: int = Field(ge=1, le=50)
    score: float | None = None
    query_count: int = Field(ge=0, le=50)
    elapsed_ms: float = Field(ge=0)

    @field_validator("score", "elapsed_ms")
    @classmethod
    def validate_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("discovery scores and timings must be finite")
        return value


class DiscoveryReadRequest(_FrozenDiscoveryModel):
    """Private reader input; query text is excluded from diagnostics and serialization."""

    sub_intent_id: UUID = Field(exclude=True, repr=False)
    query_text: str = Field(min_length=1, max_length=2_000, exclude=True, repr=False)


class RawDiscoveryCandidate(_FrozenDiscoveryModel):
    """Reader output before document-level collapse and workspace budgeting."""

    document: DocumentVersionReference = Field(exclude=True, repr=False)
    state: AuthorityState
    provenance_verified: bool
    matched_sub_intent_ids: tuple[UUID, ...] = Field(
        min_length=1, max_length=_MAX_SUB_INTENTS, exclude=True, repr=False
    )
    observations: tuple[DiscoveryLaneObservation, ...] = Field(min_length=1, max_length=3)

    @field_validator("matched_sub_intent_ids")
    @classmethod
    def validate_sub_intents(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("matched sub-intent identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_observations(self) -> RawDiscoveryCandidate:
        if len({item.lane for item in self.observations}) != len(self.observations):
            raise ValueError("raw observations must be unique per lane")
        if not self.provenance_verified and self.state is AuthorityState.ELIGIBLE:
            raise ValueError("unverified provenance cannot be eligible")
        return self


class DiscoveryDocument(_FrozenDiscoveryModel):
    """One collapsed document/version/provenance record in the broad workspace."""

    document: DocumentVersionReference = Field(exclude=True, repr=False)
    state: AuthorityState
    matched_sub_intent_ids: tuple[UUID, ...] = Field(
        min_length=1, max_length=_MAX_SUB_INTENTS, exclude=True, repr=False
    )
    observations: tuple[DiscoveryLaneObservation, ...] = Field(min_length=1, max_length=3)
    supporting_candidate_count: int = Field(ge=1)

    @field_validator("matched_sub_intent_ids")
    @classmethod
    def validate_sub_intents(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("collapsed sub-intent identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_observations(self) -> DiscoveryDocument:
        if len({item.lane for item in self.observations}) != len(self.observations):
            raise ValueError("collapsed observations must be unique per lane")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "matched_sub_intent_count": len(self.matched_sub_intent_ids),
            "lanes": [item.lane.value for item in self.observations],
            "supporting_candidate_count": self.supporting_candidate_count,
        }


class BroadDiscoveryWorkspace(_FrozenDiscoveryModel):
    """Bounded discovery recall workspace; it deliberately has no final-evidence decision."""

    documents: tuple[DiscoveryDocument, ...] = Field(default=(), max_length=_MAX_WORKSPACE)
    workspace_limit: int = Field(ge=15, le=_MAX_WORKSPACE)
    raw_candidate_count: int = Field(default=0, ge=0)
    provenance_filtered_count: int = Field(default=0, ge=0)
    final_evidence_selected: Literal[False] = False

    @model_validator(mode="after")
    def validate_workspace(self) -> BroadDiscoveryWorkspace:
        identities = [item.document for item in self.documents]
        if len(set(identities)) != len(identities):
            raise ValueError("workspace documents must be unique by full identity")
        if len(self.documents) > self.workspace_limit:
            raise ValueError("workspace cannot exceed its configured limit")
        return self

    def to_public_dict(self) -> dict[str, object]:
        lane_counts = {lane.value: 0 for lane in DiscoveryLane}
        for document in self.documents:
            for observation in document.observations:
                lane_counts[observation.lane.value] += 1
        return {
            "workspace_document_count": len(self.documents),
            "workspace_limit": self.workspace_limit,
            "raw_candidate_count": self.raw_candidate_count,
            "provenance_filtered_count": self.provenance_filtered_count,
            "lane_document_counts": lane_counts,
            "final_evidence_selected": self.final_evidence_selected,
        }


__all__ = [
    "BroadDiscoveryWorkspace",
    "DiscoveryDocument",
    "DiscoveryLane",
    "DiscoveryLaneObservation",
    "DiscoveryOutcome",
    "DiscoveryReadRequest",
    "DiscoverySettings",
    "RawDiscoveryCandidate",
]
