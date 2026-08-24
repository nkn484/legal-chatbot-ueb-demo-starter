"""Immutable, channel-neutral contracts for bounded conversation state."""

from enum import StrEnum
from typing import Final
from unicodedata import category, normalize
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.chat.models import (
    CONVERSATION_CONTEXT_TURN_LIMIT,
    ChatOutcome,
    ChatReasonCode,
    GroundedChatResult,
)
from legal_chatbot.retrieval.models import TemporalScope

USER_TEXT_MAX_CHARS: Final = 4_000
ASSISTANT_TEXT_MAX_CHARS: Final = 4_000
DELIVERY_ID_MAX_CHARS: Final = 256
ROLLING_SUMMARY_MAX_CHARS: Final = 1_500
ACTIVE_TOPIC_MAX_CHARS: Final = 256
REFERENCE_LIMIT_PER_KIND: Final = 6
RETAINED_EXCHANGE_LIMIT: Final = 32
RETENTION_SECONDS: Final = 604_800
PROCESSING_LEASE_SECONDS: Final = 120


class _FrozenConversationModel(BaseModel):
    """Value-like contracts that reject unknown data without echoing it in errors."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ConversationExchangeStatus(StrEnum):
    """Persisted lifecycle states for one idempotent delivery."""

    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class ConversationReferenceKind(StrEnum):
    """Kinds of server-owned identities retained with conversation state."""

    CITATION = "CITATION"
    DOCUMENT = "DOCUMENT"


class ConversationTurnRole(StrEnum):
    """The only roles retained by the conversation boundary."""

    USER = "USER"
    ASSISTANT = "ASSISTANT"


class ConversationReservationStatus(StrEnum):
    """Outcomes of atomically reserving one idempotent delivery."""

    RESERVED = "RESERVED"
    DUPLICATE_COMPLETED = "DUPLICATE_COMPLETED"
    DUPLICATE_PROCESSING = "DUPLICATE_PROCESSING"
    DUPLICATE_TERMINAL = "DUPLICATE_TERMINAL"


_REFUSAL_REASONS: Final = frozenset(
    {
        ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE,
        ChatReasonCode.INVALID_EVIDENCE_CHAIN,
        ChatReasonCode.RETRIEVAL_FAILURE,
        ChatReasonCode.GROUNDING_FAILURE,
        ChatReasonCode.PROVIDER_FAILURE,
        ChatReasonCode.INVALID_PROVIDER_OUTPUT,
        ChatReasonCode.CITATION_REVALIDATION_FAILURE,
    }
)


def _normalize_safe_text(value: object, *, field_name: str) -> object:
    """NFC-normalize, trim, and reject control-bearing or blank strings."""

    if not isinstance(value, str):
        return value
    normalized = normalize("NFC", value).strip()
    if not normalized or any(category(character).startswith("C") for character in normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


class CreateConversationResult(_FrozenConversationModel):
    """Identity allocated for a newly created conversation."""

    conversation_id: UUID


class ConversationRequest(_FrozenConversationModel):
    """One channel delivery submitted to a known conversation."""

    conversation_id: UUID
    delivery_id: str = Field(max_length=DELIVERY_ID_MAX_CHARS)
    text: str = Field(max_length=USER_TEXT_MAX_CHARS)
    temporal_scope: TemporalScope = TemporalScope.NONE

    @field_validator("delivery_id", "text", mode="before")
    @classmethod
    def normalize_required_text(cls, value: object, info) -> object:
        return _normalize_safe_text(value, field_name=info.field_name)


class ConversationReference(_FrozenConversationModel):
    """One bounded citation or document identity retained in state."""

    kind: ConversationReferenceKind
    reference_id: UUID
    ordinal: int = Field(ge=0, le=REFERENCE_LIMIT_PER_KIND - 1)


class ConversationTurn(_FrozenConversationModel):
    """One completed user or assistant turn in chronological ordinal order."""

    ordinal: int = Field(ge=1)
    role: ConversationTurnRole
    text: str = Field(max_length=USER_TEXT_MAX_CHARS)
    outcome: ChatOutcome | None = None
    reason: ChatReasonCode | None = None

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return _normalize_safe_text(value, field_name="conversation turn text")

    @model_validator(mode="after")
    def validate_turn_shape(self) -> "ConversationTurn":
        if self.role is ConversationTurnRole.USER:
            if self.outcome is not None or self.reason is not None:
                raise ValueError("user turn must not include an outcome or reason")
            return self

        if self.outcome is None or self.reason is None:
            raise ValueError("assistant turn requires an outcome and reason")
        if self.outcome is ChatOutcome.ANSWER and self.reason is ChatReasonCode.ANSWER_GROUNDED:
            return self
        if self.outcome is ChatOutcome.CLARIFICATION and self.reason is ChatReasonCode.NO_RESULTS:
            return self
        if self.outcome is ChatOutcome.REFUSAL and self.reason in _REFUSAL_REASONS:
            return self
        raise ValueError("assistant turn outcome and reason are invalid")


class ConversationStateSnapshot(_FrozenConversationModel):
    """Bounded durable state supplied to conversation orchestration."""

    state_version: int = Field(ge=0)
    rolling_summary: str | None = Field(default=None, max_length=ROLLING_SUMMARY_MAX_CHARS)
    active_topic: str | None = Field(default=None, max_length=ACTIVE_TOPIC_MAX_CHARS)
    recent_turns: tuple[ConversationTurn, ...] = Field(
        default=(), max_length=CONVERSATION_CONTEXT_TURN_LIMIT
    )
    references: tuple[ConversationReference, ...] = Field(
        default=(), max_length=REFERENCE_LIMIT_PER_KIND * len(ConversationReferenceKind)
    )

    @field_validator("rolling_summary", "active_topic", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_safe_text(value, field_name="conversation state")

    @model_validator(mode="after")
    def validate_snapshot_bounds(self) -> "ConversationStateSnapshot":
        ordinals = tuple(turn.ordinal for turn in self.recent_turns)
        if any(left >= right for left, right in zip(ordinals, ordinals[1:], strict=False)):
            raise ValueError("conversation turn ordinals are invalid")

        references_by_kind = {kind: 0 for kind in ConversationReferenceKind}
        reference_keys = {(reference.kind, reference.reference_id) for reference in self.references}
        if len(reference_keys) != len(self.references):
            raise ValueError("conversation references must be unique by kind and identity")
        reference_ordinal_keys = {
            (reference.kind, reference.ordinal) for reference in self.references
        }
        if len(reference_ordinal_keys) != len(self.references):
            raise ValueError("conversation references must be unique by kind and ordinal")
        for reference in self.references:
            references_by_kind[reference.kind] += 1
        if any(count > REFERENCE_LIMIT_PER_KIND for count in references_by_kind.values()):
            raise ValueError("conversation references exceed the per-kind limit")
        return self


class ConversationResult(_FrozenConversationModel):
    """The idempotent lifecycle result returned without channel-specific details."""

    conversation_id: UUID
    exchange_id: UUID
    status: ConversationExchangeStatus
    duplicate: bool
    chat: GroundedChatResult | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "ConversationResult":
        if self.status is ConversationExchangeStatus.COMPLETED:
            if self.chat is None:
                raise ValueError("completed result requires chat")
        elif self.chat is not None:
            raise ValueError("non-completed result must not include chat")
        if self.duplicate and self.status not in {
            ConversationExchangeStatus.PROCESSING,
            ConversationExchangeStatus.COMPLETED,
        }:
            raise ValueError("duplicate result has an invalid lifecycle state")
        return self


class ConversationCompactionCandidate(_FrozenConversationModel):
    """One terminal exchange eligible for server-authorized state compaction."""

    exchange_id: UUID
    ordinal: int = Field(ge=1)
    status: ConversationExchangeStatus
    user_text: str = Field(max_length=USER_TEXT_MAX_CHARS)
    assistant_text: str | None = Field(default=None, max_length=ASSISTANT_TEXT_MAX_CHARS)
    chat_outcome: ChatOutcome | None = None
    chat_reason: str | None = Field(default=None, max_length=64)
    citation_count: int = Field(ge=0, le=REFERENCE_LIMIT_PER_KIND)
    document_count: int = Field(ge=0, le=REFERENCE_LIMIT_PER_KIND)

    @field_validator("user_text", "assistant_text", "chat_reason", mode="before")
    @classmethod
    def normalize_optional_candidate_text(cls, value: object, info) -> object:
        if value is None:
            return None
        return _normalize_safe_text(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_terminal_candidate_shape(self) -> "ConversationCompactionCandidate":
        if self.status is ConversationExchangeStatus.COMPLETED:
            if self.assistant_text is None or self.chat_outcome is None or self.chat_reason is None:
                raise ValueError("completed compaction candidate is incomplete")
        elif self.status in {
            ConversationExchangeStatus.FAILED,
            ConversationExchangeStatus.ABANDONED,
        }:
            if self.assistant_text is not None or self.chat_outcome is not None:
                raise ValueError("failed compaction candidate has result fields")
        else:
            raise ValueError("compaction candidate status must be terminal")
        return self


class ConversationCompactionPlan(_FrozenConversationModel):
    """The exact oldest terminal exchange sequence authorized for compaction."""

    exchange_ids: tuple[UUID, ...] = ()
    candidates: tuple[ConversationCompactionCandidate, ...] = ()

    @model_validator(mode="after")
    def validate_exact_candidate_order(self) -> "ConversationCompactionPlan":
        if len(set(self.exchange_ids)) != len(self.exchange_ids):
            raise ValueError("compaction exchange IDs must be unique")
        if self.exchange_ids != tuple(candidate.exchange_id for candidate in self.candidates):
            raise ValueError("compaction exchange IDs and candidates must match in order")
        return self


class ConversationReservation(_FrozenConversationModel):
    """A version-bound processing reservation with bounded state and compaction plan."""

    conversation_id: UUID
    exchange_id: UUID
    ordinal: int = Field(ge=1)
    expected_state_version: int = Field(ge=0)
    snapshot: ConversationStateSnapshot
    compaction_plan: ConversationCompactionPlan = Field(default_factory=ConversationCompactionPlan)


class PersistedConversationExchange(_FrozenConversationModel):
    """Completed exchange pointers retained for deterministic replay re-resolution."""

    conversation_id: UUID
    exchange_id: UUID
    ordinal: int = Field(ge=1)
    status: ConversationExchangeStatus
    assistant_text: str = Field(max_length=ASSISTANT_TEXT_MAX_CHARS)
    chat_outcome: ChatOutcome
    chat_reason: ChatReasonCode
    retrieval_run_id: UUID | None = None
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=128)
    references: tuple[ConversationReference, ...] = Field(
        default=(), max_length=REFERENCE_LIMIT_PER_KIND * len(ConversationReferenceKind)
    )

    @field_validator("assistant_text", mode="before")
    @classmethod
    def normalize_assistant_text(cls, value: object) -> object:
        return _normalize_safe_text(value, field_name="assistant text")

    @field_validator("provider_request_id")
    @classmethod
    def validate_provider_request_id(cls, value: str | None) -> str | None:
        if value is not None and (
            not value or any(not "!" <= character <= "~" for character in value)
        ):
            raise ValueError("provider request ID is invalid")
        return value

    @property
    def citation_ids(self) -> tuple[UUID, ...]:
        """Citation identities in persisted ordinal order, without citation metadata."""

        return tuple(
            reference.reference_id
            for reference in self.references
            if reference.kind is ConversationReferenceKind.CITATION
        )

    @property
    def document_ids(self) -> tuple[UUID, ...]:
        """Document identities in persisted ordinal order, without document metadata."""

        return tuple(
            reference.reference_id
            for reference in self.references
            if reference.kind is ConversationReferenceKind.DOCUMENT
        )

    @model_validator(mode="after")
    def validate_completed_exchange_shape(self) -> "PersistedConversationExchange":
        if self.status is not ConversationExchangeStatus.COMPLETED:
            raise ValueError("persisted exchange status must be completed")

        reference_keys = {(reference.kind, reference.reference_id) for reference in self.references}
        if len(reference_keys) != len(self.references):
            raise ValueError("conversation references must be unique by kind and identity")
        reference_ordinal_keys = {
            (reference.kind, reference.ordinal) for reference in self.references
        }
        if len(reference_ordinal_keys) != len(self.references):
            raise ValueError("conversation references must be unique by kind and ordinal")
        if (
            tuple(
                sorted(
                    self.references, key=lambda reference: (reference.kind.value, reference.ordinal)
                )
            )
            != self.references
        ):
            raise ValueError("conversation references must be ordered by kind and ordinal")
        references_by_kind = {kind: 0 for kind in ConversationReferenceKind}
        for reference in self.references:
            references_by_kind[reference.kind] += 1
        if any(count > REFERENCE_LIMIT_PER_KIND for count in references_by_kind.values()):
            raise ValueError("conversation references exceed the per-kind limit")

        provider_metadata_present = (
            self.provider is not None
            or self.model is not None
            or self.provider_request_id is not None
        )
        if self.chat_outcome is ChatOutcome.ANSWER:
            if (
                self.chat_reason is not ChatReasonCode.ANSWER_GROUNDED
                or self.retrieval_run_id is None
                or not self.citation_ids
                or self.provider is None
                or self.model is None
            ):
                raise ValueError("invalid persisted answer exchange")
        elif self.chat_outcome is ChatOutcome.CLARIFICATION:
            if (
                self.chat_reason is not ChatReasonCode.NO_RESULTS
                or self.retrieval_run_id is None
                or self.references
                or provider_metadata_present
            ):
                raise ValueError("invalid persisted clarification exchange")
        elif (
            self.chat_reason not in _REFUSAL_REASONS
            or self.references
            or provider_metadata_present
            or (
                self.chat_reason is not ChatReasonCode.RETRIEVAL_FAILURE
                and self.retrieval_run_id is None
            )
        ):
            raise ValueError("invalid persisted refusal exchange")
        return self


class ConversationReservationResult(_FrozenConversationModel):
    """Reservation result whose payload is determined solely by its status."""

    status: ConversationReservationStatus
    reservation: ConversationReservation | None = None
    completed: PersistedConversationExchange | None = None
    conversation_id: UUID | None = None
    exchange_id: UUID | None = None

    @model_validator(mode="after")
    def validate_reservation_result_shape(self) -> "ConversationReservationResult":
        if self.status is ConversationReservationStatus.RESERVED:
            if (
                self.reservation is None
                or self.completed is not None
                or self.conversation_id is not None
                or self.exchange_id is not None
            ):
                raise ValueError("reserved result requires only a reservation")
        elif self.status is ConversationReservationStatus.DUPLICATE_COMPLETED:
            if (
                self.completed is None
                or self.reservation is not None
                or self.conversation_id is not None
                or self.exchange_id is not None
            ):
                raise ValueError("completed duplicate result requires only a completed exchange")
        elif (
            self.reservation is not None
            or self.completed is not None
            or self.conversation_id is None
            or self.exchange_id is None
        ):
            raise ValueError("processing and terminal duplicates require only identity pointers")
        return self


class ConversationStateUpdate(_FrozenConversationModel):
    """Version-bound summary and topic values to persist with a completed exchange."""

    expected_state_version: int = Field(ge=0)
    rolling_summary: str | None = Field(default=None, max_length=ROLLING_SUMMARY_MAX_CHARS)
    active_topic: str | None = Field(default=None, max_length=ACTIVE_TOPIC_MAX_CHARS)
    compacted_exchange_ids: tuple[UUID, ...] = Field(default=(), max_length=RETAINED_EXCHANGE_LIMIT)

    @field_validator("rolling_summary", "active_topic", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return _normalize_safe_text(value, field_name="conversation state update")

    @model_validator(mode="after")
    def validate_compacted_exchange_ids(self) -> "ConversationStateUpdate":
        if len(set(self.compacted_exchange_ids)) != len(self.compacted_exchange_ids):
            raise ValueError("compacted exchange IDs must be unique and ordered")
        return self
