"""Private, immutable evidence-shaping contracts for the Phase-A hypothesis."""

from enum import StrEnum
from math import isfinite
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _FrozenContract(BaseModel):
    """Value-like contract which rejects accidental persistence or runtime fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceId(StrEnum):
    """Registry identifiers only; this enum makes no active-status or authority claim."""

    VBQPPL = "VBQPPL"
    VNU = "VNU"
    UEB = "UEB"


class SourceBinding(StrEnum):
    """A user-cue observation, not a retrieval permission or authority statement."""

    VBQPPL = "VBQPPL"
    VNU = "VNU"
    UEB = "UEB"
    UNKNOWN = "UNKNOWN"
    AMBIGUOUS = "AMBIGUOUS"


class ProvenanceType(StrEnum):
    SOURCE_FETCH = "source_fetch"
    MANUAL_SNAPSHOT = "manual_snapshot"


class TransportTrustMode(StrEnum):
    STRICT_TLS = "STRICT_TLS"


class RetrievalLane(StrEnum):
    SEMANTIC = "SEMANTIC"
    CONTENT_FTS = "CONTENT_FTS"
    TITLE_FTS = "TITLE_FTS"


class SourceScopeObservation(StrEnum):
    NONE = "NONE"
    EXPLICIT_SOURCE = "EXPLICIT_SOURCE"
    AMBIGUOUS_SOURCE = "AMBIGUOUS_SOURCE"


class DocumentIdentity(_FrozenContract):
    """Opaque version identity without legal authority or effect assertions."""

    document_id: UUID = Field(exclude=True, repr=False)
    document_version_id: UUID = Field(exclude=True, repr=False)
    source_id: SourceId
    external_id: str = Field(min_length=1, max_length=256, exclude=True, repr=False)
    document_number_normalized: str | None = Field(
        default=None, max_length=256, exclude=True, repr=False
    )
    title: str | None = Field(default=None, max_length=4_096, exclude=True, repr=False)
    version_number: int = Field(ge=1)
    provenance_record_id: UUID = Field(exclude=True, repr=False)
    provenance_type: ProvenanceType
    transport_trust_mode: TransportTrustMode = TransportTrustMode.STRICT_TLS
    latest_ingested: bool

    def to_public_dict(self) -> dict[str, object]:
        """Return only source-neutral, non-identifying diagnostic state."""

        return {
            "source_id": self.source_id.value,
            "version_number": self.version_number,
            "provenance_type": self.provenance_type.value,
            "transport_trust_mode": self.transport_trust_mode.value,
            "latest_ingested": self.latest_ingested,
        }


class LaneObservation(_FrozenContract):
    """Content-free observation made by one bounded retrieval lane."""

    lane: RetrievalLane
    rank: int = Field(ge=1, le=50)
    score: float | None = None
    query_count: int = Field(ge=0, le=50)
    elapsed_ms: float = Field(ge=0)
    rows_returned: int = Field(ge=0, le=50)

    @field_validator("score", "elapsed_ms")
    @classmethod
    def validate_finite(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("scores and timings must be finite")
        return value

    def to_public_dict(self) -> dict[str, object]:
        return self.model_dump()


class CandidateEvidence(_FrozenContract):
    """A child chunk candidate; it is never a collapsed document result."""

    chunk_id: UUID = Field(exclude=True, repr=False)
    identity: DocumentIdentity
    ordinal: int = Field(ge=0)
    observations: tuple[LaneObservation, ...] = Field(min_length=1, max_length=3)
    unit_ids: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    supporting_semantic_score: float | None = Field(default=None, exclude=True, repr=False)
    source_scope: SourceScopeObservation
    eligible: bool
    rejection_code: str | None = Field(default=None, max_length=64)

    @field_validator("unit_ids")
    @classmethod
    def validate_unit_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("unit_ids must be unique")
        if any(not unit_id.strip() for unit_id in value):
            raise ValueError("unit_ids must not contain blank values")
        return value

    @field_validator("supporting_semantic_score")
    @classmethod
    def validate_supporting_semantic_score(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("supporting_semantic_score must be finite")
        return value

    @model_validator(mode="after")
    def validate_observations_and_eligibility(self) -> "CandidateEvidence":
        if len({observation.lane for observation in self.observations}) != len(self.observations):
            raise ValueError("observations must be unique per lane")
        if self.eligible and self.rejection_code is not None:
            raise ValueError("eligible candidates cannot have a rejection_code")
        if not self.eligible and self.rejection_code is None:
            raise ValueError("ineligible candidates require a rejection_code")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.to_public_dict(),
            "ordinal": self.ordinal,
            "observations": [observation.to_public_dict() for observation in self.observations],
            "unit_id_count": len(self.unit_ids),
            "source_scope": self.source_scope.value,
            "eligible": self.eligible,
            "rejection_code": self.rejection_code,
        }


class LaneAggregate(_FrozenContract):
    """Best rank and score from one lane after document collapse."""

    lane: RetrievalLane
    best_rank: int | None = Field(default=None, ge=1, le=50)
    best_score: float | None = None

    @field_validator("best_score")
    @classmethod
    def validate_finite_score(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("best_score must be finite")
        return value


class OpportunityTag(_FrozenContract):
    """Opaque unit/source opportunity marker with safe count-only diagnostics."""

    unit_id: str = Field(min_length=1, max_length=256, exclude=True, repr=False)
    source_scope: SourceScopeObservation
    source_ids: tuple[SourceId, ...] = Field(default=(), max_length=1, exclude=True, repr=False)

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: tuple[SourceId, ...]) -> tuple[SourceId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_source_scope(self) -> "OpportunityTag":
        if self.source_scope is SourceScopeObservation.EXPLICIT_SOURCE:
            if len(self.source_ids) != 1:
                raise ValueError("EXPLICIT_SOURCE requires exactly one source_id")
        elif self.source_ids:
            raise ValueError("NONE and AMBIGUOUS_SOURCE cannot resolve source_ids")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {"source_scope": self.source_scope.value, "source_count": len(self.source_ids)}


class CollapsedDocumentCandidate(_FrozenContract):
    """One representative child candidate plus content-free document-level evidence."""

    identity: DocumentIdentity
    representative: CandidateEvidence
    supporting_chunk_count: int = Field(ge=0)
    best_chunk_rank: int | None = Field(default=None, ge=1, le=50)
    best_chunk_score: float | None = None
    lane_aggregates: tuple[LaneAggregate, ...] = Field(default=(), max_length=3)
    merged_unit_ids: tuple[str, ...] = Field(default=(), max_length=4, exclude=True, repr=False)
    opportunity_unit_ids: tuple[str, ...] = Field(
        default=(), max_length=4, exclude=True, repr=False
    )
    opportunity_tags: tuple[OpportunityTag, ...] = Field(default=(), max_length=4)
    fusion_score: float | None = None

    @field_validator("best_chunk_score", "fusion_score")
    @classmethod
    def validate_finite_scores(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("scores must be finite")
        return value

    @field_validator("opportunity_unit_ids")
    @classmethod
    def validate_unit_opportunities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("opportunity_unit_ids must be unique")
        return value

    @field_validator("merged_unit_ids")
    @classmethod
    def validate_merged_unit_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("merged_unit_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_representative_identity(self) -> "CollapsedDocumentCandidate":
        if self.identity != self.representative.identity:
            raise ValueError("identity must fully match the representative")
        if len({aggregate.lane for aggregate in self.lane_aggregates}) != len(
            self.lane_aggregates
        ):
            raise ValueError("lane_aggregates must be unique per lane")
        if len({tag.unit_id for tag in self.opportunity_tags}) != len(self.opportunity_tags):
            raise ValueError("opportunity tags must be unique per unit")
        if set(tag.unit_id for tag in self.opportunity_tags) != set(self.opportunity_unit_ids):
            raise ValueError("opportunity tags must exactly cover opportunity_unit_ids")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "identity": self.identity.to_public_dict(),
            "supporting_chunk_count": self.supporting_chunk_count,
            "best_chunk_rank": self.best_chunk_rank,
            "best_chunk_score": self.best_chunk_score,
            "lane_aggregates": [aggregate.model_dump() for aggregate in self.lane_aggregates],
            "merged_unit_count": len(self.merged_unit_ids),
            "opportunity_unit_count": len(self.opportunity_unit_ids),
            "opportunity_tags": [tag.to_public_dict() for tag in self.opportunity_tags],
            "fusion_score": self.fusion_score,
        }
