"""Immutable in-memory contracts for lexical retrieval evidence."""

from enum import StrEnum
from math import isfinite
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.sources.models import ProvenanceType, TransportTrustMode

LEXICAL_STRATEGY: Final = "postgresql_fts"
LEXICAL_STRATEGY_VERSION: Final = "v1"
QUERY_MAX_CHARS: Final = 4_000
EXPANSION_QUERY_MAX_CHARS: Final = QUERY_MAX_CHARS
EXPANSION_DOCUMENT_IDS_MAX_COUNT: Final = 2


class _FrozenRetrievalModel(BaseModel):
    """Base for value-like retrieval contracts with no persistence dependencies."""

    model_config = ConfigDict(frozen=True)


class RetrievalScope(StrEnum):
    """Document-version scope available in the initial retrieval slice."""

    LATEST_INGESTED = "LATEST_INGESTED"


class RetrievalTrustScope(StrEnum):
    """Server-owned transport trust envelope for a persisted retrieval run."""

    STRICT_TLS_ONLY = "STRICT_TLS_ONLY"
    ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION = "ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION"


class EvidenceTrustLabel(StrEnum):
    """Safe evidence disclosure derived only from persisted transport trust."""

    OFFICIAL_LEGAL = "OFFICIAL_LEGAL"
    OFFICIAL_LEGAL_PINNED_EXCEPTION = "OFFICIAL_LEGAL_PINNED_EXCEPTION"
    MANUAL_SNAPSHOT = "MANUAL_SNAPSHOT"


def coerce_transport_trust_mode(value: object) -> TransportTrustMode:
    """Normalize persisted transport trust values at the retrieval contract boundary."""

    if isinstance(value, TransportTrustMode):
        return value
    if isinstance(value, str):
        return TransportTrustMode(value)
    raise ValueError("invalid transport trust mode")


def coerce_provenance_type(value: object) -> ProvenanceType:
    """Normalize persisted provenance without leaking source-module imports to adapters."""

    if isinstance(value, ProvenanceType):
        return value
    if isinstance(value, str):
        return ProvenanceType(value)
    raise ValueError("invalid provenance type")


def eligible_transport_trust_modes(scope: RetrievalTrustScope) -> tuple[TransportTrustMode, ...]:
    """Return the only provenance modes eligible for a server-selected trust scope."""

    if scope is RetrievalTrustScope.STRICT_TLS_ONLY:
        return (TransportTrustMode.STRICT_TLS,)
    if scope is RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION:
        return (
            TransportTrustMode.STRICT_TLS,
            TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION,
        )
    raise ValueError("unsupported retrieval trust scope")


def evidence_trust_label_for(
    transport_trust_mode: TransportTrustMode,
    provenance_type: ProvenanceType = ProvenanceType.SOURCE_FETCH,
) -> EvidenceTrustLabel:
    """Derive authority disclosure from acquisition provenance and transport trust."""

    if (
        provenance_type is ProvenanceType.MANUAL_SNAPSHOT
        and transport_trust_mode is TransportTrustMode.STRICT_TLS
    ):
        return EvidenceTrustLabel.MANUAL_SNAPSHOT
    if (
        provenance_type is ProvenanceType.SOURCE_FETCH
        and transport_trust_mode is TransportTrustMode.STRICT_TLS
    ):
        return EvidenceTrustLabel.OFFICIAL_LEGAL
    if (
        provenance_type is ProvenanceType.SOURCE_FETCH
        and transport_trust_mode is TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION
    ):
        return EvidenceTrustLabel.OFFICIAL_LEGAL_PINNED_EXCEPTION
    raise ValueError("provenance and transport trust are not eligible evidence")


def is_transport_trust_eligible(
    scope: RetrievalTrustScope, transport_trust_mode: TransportTrustMode
) -> bool:
    """Fail closed for malformed, legacy, or out-of-scope provenance trust."""

    return transport_trust_mode in eligible_transport_trust_modes(scope)


def is_evidence_provenance_eligible(
    scope: RetrievalTrustScope,
    transport_trust_mode: TransportTrustMode,
    provenance_type: ProvenanceType,
) -> bool:
    """Require both an eligible transport and a non-misleading authority label."""

    if not is_transport_trust_eligible(scope, transport_trust_mode):
        return False
    try:
        evidence_trust_label_for(transport_trust_mode, provenance_type)
    except ValueError:
        return False
    return True


class RetrievalDecision(StrEnum):
    """Retrieval-level evidence outcomes, not legal-answer outcomes."""

    EVIDENCE_AVAILABLE = "EVIDENCE_AVAILABLE"
    NO_RESULTS = "NO_RESULTS"
    UNSUPPORTED_TEMPORAL_SCOPE = "UNSUPPORTED_TEMPORAL_SCOPE"
    INVALID_EVIDENCE_CHAIN = "INVALID_EVIDENCE_CHAIN"


class TemporalScope(StrEnum):
    """Temporal intent represented for a later fail-closed retrieval runtime."""

    NONE = "NONE"
    AS_OF = "AS_OF"
    CURRENT_EFFECT = "CURRENT_EFFECT"


class RetrievalReason(StrEnum):
    """Stable retrieval-level reason codes safe for persistence and callers."""

    LEXICAL_EVIDENCE_AVAILABLE = "LEXICAL_EVIDENCE_AVAILABLE"
    NO_LEXICAL_MATCH = "NO_LEXICAL_MATCH"
    SEMANTIC_EVIDENCE_AVAILABLE = "SEMANTIC_EVIDENCE_AVAILABLE"
    HYBRID_EVIDENCE_AVAILABLE = "HYBRID_EVIDENCE_AVAILABLE"
    NO_SEMANTIC_MATCH = "NO_SEMANTIC_MATCH"
    NO_HYBRID_MATCH = "NO_HYBRID_MATCH"
    SEMANTIC_UNAVAILABLE = "SEMANTIC_UNAVAILABLE"
    TEMPORAL_SCOPE_UNSUPPORTED = "TEMPORAL_SCOPE_UNSUPPORTED"
    INVALID_EVIDENCE_CHAIN = "INVALID_EVIDENCE_CHAIN"


class RetrievalRequest(_FrozenRetrievalModel):
    """Bounded in-memory retrieval input; the query must never be persisted here."""

    query: str = Field(max_length=QUERY_MAX_CHARS)
    scope: RetrievalScope = RetrievalScope.LATEST_INGESTED
    trust_scope: RetrievalTrustScope = RetrievalTrustScope.STRICT_TLS_ONLY
    top_k: int = Field(default=10, ge=1, le=20)
    temporal_scope: TemporalScope = TemporalScope.NONE
    expansion_query: str | None = Field(
        default=None,
        max_length=EXPANSION_QUERY_MAX_CHARS,
        exclude=True,
        repr=False,
    )
    expansion_document_ids: tuple[UUID, ...] = Field(
        default=(),
        max_length=EXPANSION_DOCUMENT_IDS_MAX_COUNT,
        exclude=True,
        repr=False,
    )

    @field_validator("query", mode="before")
    @classmethod
    def strip_and_validate_query(cls, value: object) -> object:
        """Normalize whitespace at the boundary and reject an empty query."""

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("query must not be blank")
            return stripped
        return value

    @field_validator("expansion_query", mode="before")
    @classmethod
    def strip_and_validate_expansion_query(cls, value: object) -> object:
        """Keep the bounded server-built expansion out of persistence representations."""

        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("expansion_query must not be blank")
            return stripped
        return value

    @field_validator("expansion_document_ids")
    @classmethod
    def validate_expansion_document_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        """Prevent planner-controlled widening beyond the two resolved anchors."""

        if len(set(value)) != len(value):
            raise ValueError("expansion_document_ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_expansion_consistency(self) -> "RetrievalRequest":
        """Require expansion text and its server-resolved document scope together."""

        if self.expansion_query is None and self.expansion_document_ids:
            raise ValueError("expansion_document_ids require expansion_query")
        if self.expansion_query is not None and self.expansion_query == self.query:
            raise ValueError("expansion_query must differ from query")
        return self


class RetrievalCandidate(_FrozenRetrievalModel):
    """A lexically ranked chunk paired with server-assigned citation identity."""

    citation_id: UUID
    document_chunk_id: UUID
    rank: int = Field(ge=1)
    lexical_score: float | None = Field(default=None, ge=0)
    semantic_score: float | None = Field(default=None, ge=-1, le=1)
    reranker_score: float | None = None

    @field_validator("lexical_score")
    @classmethod
    def validate_finite_score(cls, value: float | None) -> float | None:
        """Reject non-finite scores before they affect deterministic evidence ordering."""

        if value is not None and not isfinite(value):
            raise ValueError("lexical_score must be finite")
        return value

    @field_validator("semantic_score")
    @classmethod
    def validate_finite_semantic_score(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("semantic_score must be finite")
        return value

    @field_validator("reranker_score")
    @classmethod
    def validate_finite_reranker_score(cls, value: float | None) -> float | None:
        """Accept only a finite supplemental component without making calibration claims."""

        if value is not None and not isfinite(value):
            raise ValueError("reranker_score must be finite")
        return value

    @model_validator(mode="after")
    def validate_at_least_one_score(self) -> "RetrievalCandidate":
        if self.lexical_score is None and self.semantic_score is None:
            raise ValueError("at least one score is required")
        return self


class RetrievalResult(_FrozenRetrievalModel):
    """Opaque run evidence with counts tied exactly to its candidate tuple."""

    retrieval_run_id: UUID
    candidates: tuple[RetrievalCandidate, ...]
    candidate_count: int = Field(ge=0)
    citation_count: int = Field(ge=0)
    decision: RetrievalDecision
    reason: RetrievalReason
    # Request-scoped private state may be carried from an opt-in retrieval adapter
    # to synthesis. RetrievalService reattaches it after public-contract validation.
    quality_context: object | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_counts_and_decision(self) -> "RetrievalResult":
        """Prevent results whose declared decision contradicts their evidence."""

        candidate_total = len(self.candidates)
        if self.candidate_count != candidate_total:
            raise ValueError("candidate_count must equal the number of candidates")
        if self.citation_count != candidate_total:
            raise ValueError("citation_count must equal the number of candidates")
        if len({candidate.citation_id for candidate in self.candidates}) != candidate_total:
            raise ValueError("candidate citation IDs must be unique")
        if len({candidate.document_chunk_id for candidate in self.candidates}) != candidate_total:
            raise ValueError("candidate document chunk IDs must be unique")
        expected_ranks = tuple(range(1, candidate_total + 1))
        if tuple(candidate.rank for candidate in self.candidates) != expected_ranks:
            raise ValueError("candidate ranks must be exactly 1 through N in tuple order")

        no_evidence_decisions = {
            RetrievalDecision.NO_RESULTS,
            RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
            RetrievalDecision.INVALID_EVIDENCE_CHAIN,
        }
        if self.decision in no_evidence_decisions and candidate_total:
            raise ValueError("this decision must not include candidates or citations")
        if self.decision is RetrievalDecision.EVIDENCE_AVAILABLE and not candidate_total:
            raise ValueError("evidence_available requires at least one candidate and citation")
        return self


class ResolvedCitation(_FrozenRetrievalModel):
    """Resolved immutable citation metadata, deliberately excluding chunk content."""

    citation_id: UUID
    retrieval_run_id: UUID
    document_chunk_id: UUID
    document_version_id: UUID
    document_id: UUID
    source_provenance_record_id: UUID
    provenance_type: ProvenanceType = ProvenanceType.SOURCE_FETCH
    transport_trust_mode: TransportTrustMode = TransportTrustMode.STRICT_TLS
    evidence_trust_label: EvidenceTrustLabel = EvidenceTrustLabel.OFFICIAL_LEGAL
    source_id: str = Field(min_length=1, max_length=32)
    external_id: str = Field(min_length=1, max_length=256)
    document_number: str | None = Field(default=None, min_length=1, max_length=256)
    title: str | None = Field(default=None, min_length=1, max_length=4_096)
    canonical_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    locator: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_derived_transport_trust_label(self) -> "ResolvedCitation":
        """Allow only eligible provenance and its exact, non-sensitive disclosure label."""

        if self.evidence_trust_label is not evidence_trust_label_for(
            self.transport_trust_mode, self.provenance_type
        ):
            raise ValueError("evidence_trust_label must match transport_trust_mode")
        return self
