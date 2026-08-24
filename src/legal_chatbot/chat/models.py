"""Immutable, provider-neutral contracts for the M06 grounded-chat seam."""

import re
from enum import StrEnum
from typing import Final, Literal
from unicodedata import category, normalize
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.chat.errors import ProviderOutputFailureClass
from legal_chatbot.providers.models import sanitize_request_id
from legal_chatbot.retrieval.models import ResolvedCitation, TemporalScope

QUESTION_MAX_CHARS: Final = 4_000
MAX_CITATIONS: Final = 6
DEFAULT_MAX_CITATIONS: Final = 3
EXCERPT_MAX_CHARS: Final = 2_000
TOTAL_EVIDENCE_MAX_CHARS: Final = 6_000
PROMPT_MAX_CHARS: Final = 12_000
MAX_OUTPUT_TOKENS: Final = 384
ANSWER_MAX_CHARS: Final = 4_000
CONVERSATION_CONTEXT_MAX_CHARS: Final = 1_000
CONVERSATION_CONTEXT_TURN_LIMIT: Final = 4
CONVERSATION_CONTEXT_TURN_TEXT_MAX_CHARS: Final = 4_000
CONVERSATION_CONTEXT_SUMMARY_MAX_CHARS: Final = 1_500
CONVERSATION_CONTEXT_TOPIC_MAX_CHARS: Final = 256

_URL_SCHEME_PATTERN: Final = re.compile(
    r"\b(?:https?|ftp|mailto|file|data|javascript|tel):", re.IGNORECASE
)
_CANONICAL_UUID_PATTERN: Final = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_EVIDENCE_TOKEN_PATTERN: Final = re.compile(r"(?:\[E[1-9][0-9]*\]|\bE[1-9][0-9]*\b)", re.IGNORECASE)
_ALLOWED_ANSWER_FORMATTING_CONTROLS: Final = frozenset({"\n", "\r", "\t"})


class _FrozenChatModel(BaseModel):
    """Value-like contracts that reject unknown input without exposing it in errors."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ChatOutcome(StrEnum):
    """The only outcomes the grounded-chat service may return."""

    ANSWER = "ANSWER"
    CLARIFICATION = "CLARIFICATION"
    REFUSAL = "REFUSAL"


class ChatReasonCode(StrEnum):
    """Stable, content-free reasons for a chat outcome."""

    ANSWER_ELIGIBLE = "ANSWER_ELIGIBLE"
    ANSWER_GROUNDED = "ANSWER_GROUNDED"
    NO_RESULTS = "NO_RESULTS"
    UNSUPPORTED_TEMPORAL_SCOPE = "UNSUPPORTED_TEMPORAL_SCOPE"
    INVALID_EVIDENCE_CHAIN = "INVALID_EVIDENCE_CHAIN"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"
    CITATION_REVALIDATION_FAILURE = "CITATION_REVALIDATION_FAILURE"


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


def _normalized_nonblank(value: object, *, field_name: str) -> object:
    """NFC-normalize string values and keep validation errors free of their content."""

    if not isinstance(value, str):
        return value
    normalized = normalize("NFC", value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is invalid")
    return normalized


def classify_provider_answer_safety(value: str) -> ProviderOutputFailureClass | None:
    """Return the first unsafe answer class without retaining or exposing its content.

    Checks are ordered control, URL, UUID, evidence token, then citation ID.  This is
    the sole safety classification used by both parser diagnostics and Pydantic validation.
    """

    if any(
        category(character).startswith("C")
        and character not in _ALLOWED_ANSWER_FORMATTING_CONTROLS
        for character in value
    ):
        return ProviderOutputFailureClass.ANSWER_CONTROL
    if _URL_SCHEME_PATTERN.search(value) is not None:
        return ProviderOutputFailureClass.ANSWER_URL
    if _CANONICAL_UUID_PATTERN.search(value) is not None:
        return ProviderOutputFailureClass.ANSWER_UUID
    if _EVIDENCE_TOKEN_PATTERN.search(value) is not None:
        return ProviderOutputFailureClass.ANSWER_EVIDENCE_TOKEN
    if "citation_id" in value.casefold():
        return ProviderOutputFailureClass.ANSWER_CITATION_ID
    return None


def _validate_provider_answer(value: str) -> str:
    """Reject answer content that could introduce server-owned metadata or links."""

    if classify_provider_answer_safety(value) is not None:
        raise ValueError("answer is invalid")
    return value


def _strict_optional_request_id(value: str | None) -> str | None:
    """Reject unsafe request IDs rather than retaining their untrusted value."""

    if value is not None and sanitize_request_id(value) is None:
        raise ValueError("provider request ID is invalid")
    return value


class ConversationContextTurn(_FrozenChatModel):
    """One bounded, untrusted prior turn supplied by an external conversation boundary."""

    role: Literal["USER", "ASSISTANT"]
    text: str = Field(max_length=CONVERSATION_CONTEXT_TURN_TEXT_MAX_CHARS)
    ordinal: int = Field(ge=1)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return _normalized_nonblank(value, field_name="conversation turn text")


class ConversationContext(_FrozenChatModel):
    """Bounded, generic conversational context that remains untrusted and non-persistent in chat."""

    rolling_summary: str | None = Field(
        default=None, max_length=CONVERSATION_CONTEXT_SUMMARY_MAX_CHARS
    )
    active_topic: str | None = Field(default=None, max_length=CONVERSATION_CONTEXT_TOPIC_MAX_CHARS)
    recent_turns: tuple[ConversationContextTurn, ...] = Field(
        default=(), max_length=CONVERSATION_CONTEXT_TURN_LIMIT
    )

    @field_validator("rolling_summary", "active_topic", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return _normalized_nonblank(value, field_name="conversation context")

    @model_validator(mode="after")
    def validate_context_bounds(self) -> "ConversationContext":
        ordinals = tuple(turn.ordinal for turn in self.recent_turns)
        if any(left >= right for left, right in zip(ordinals, ordinals[1:], strict=False)):
            raise ValueError("conversation turn ordinals are invalid")
        combined_length = sum(
            len(value)
            for value in (
                self.rolling_summary,
                self.active_topic,
                *(turn.text for turn in self.recent_turns),
            )
            if value is not None
        )
        if combined_length > CONVERSATION_CONTEXT_MAX_CHARS:
            raise ValueError("conversation context exceeds the allowed bound")
        return self


class ChatRequest(_FrozenChatModel):
    """Bounded user input before deterministic temporal policy is applied."""

    question: str = Field(max_length=QUESTION_MAX_CHARS)
    retrieval_query: str | None = Field(default=None, max_length=QUESTION_MAX_CHARS)
    conversation_context: ConversationContext | None = None
    temporal_scope: TemporalScope = TemporalScope.NONE

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: object) -> object:
        return _normalized_nonblank(value, field_name="question")

    @field_validator("retrieval_query", mode="before")
    @classmethod
    def normalize_retrieval_query(cls, value: object) -> object:
        if value is None:
            return None
        return _normalized_nonblank(value, field_name="retrieval query")


class GroundingEvidenceRequest(_FrozenChatModel):
    """Citation identities requested from the grounding-evidence boundary in caller order."""

    retrieval_run_id: UUID
    citation_ids: tuple[UUID, ...] = Field(min_length=1, max_length=MAX_CITATIONS)

    @field_validator("citation_ids")
    @classmethod
    def validate_unique_citation_ids(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(set(value)) != len(value):
            raise ValueError("citation IDs must be unique")
        return value


class GroundingExcerpt(_FrozenChatModel):
    """One bounded untrusted text excerpt paired with its resolved citation metadata."""

    citation: ResolvedCitation
    text: str = Field(max_length=EXCERPT_MAX_CHARS)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return _normalized_nonblank(value, field_name="excerpt")


class GroundingEvidence(_FrozenChatModel):
    """Bounded excerpts from exactly one persisted retrieval run."""

    retrieval_run_id: UUID
    excerpts: tuple[GroundingExcerpt, ...] = Field(min_length=1, max_length=MAX_CITATIONS)

    @model_validator(mode="after")
    def validate_excerpts(self) -> "GroundingEvidence":
        citation_ids = tuple(excerpt.citation.citation_id for excerpt in self.excerpts)
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("grounding citation IDs must be unique")
        if any(
            excerpt.citation.retrieval_run_id != self.retrieval_run_id for excerpt in self.excerpts
        ):
            raise ValueError("grounding citations must match the retrieval run")
        if sum(len(excerpt.text) for excerpt in self.excerpts) > TOTAL_EVIDENCE_MAX_CHARS:
            raise ValueError("grounding text exceeds the total evidence bound")
        return self


class ProviderAnswer(_FrozenChatModel):
    """Validated prose parsed from provider output; it contains no provider metadata."""

    answer: str = Field(max_length=ANSWER_MAX_CHARS)

    @field_validator("answer", mode="before")
    @classmethod
    def normalize_answer(cls, value: object) -> object:
        return _normalized_nonblank(value, field_name="answer")

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        return _validate_provider_answer(value)


class ChatPolicyDecision(_FrozenChatModel):
    """A deterministic policy route, independent of provider or retrieval adapters."""

    outcome: ChatOutcome
    reason: ChatReasonCode
    provider_allowed: bool
    fixed_text: str | None = Field(default=None, max_length=ANSWER_MAX_CHARS)

    @field_validator("fixed_text", mode="before")
    @classmethod
    def normalize_fixed_text(cls, value: object) -> object:
        if value is None:
            return value
        return _normalized_nonblank(value, field_name="fixed text")

    @model_validator(mode="after")
    def validate_policy_route(self) -> "ChatPolicyDecision":
        if self.outcome is ChatOutcome.ANSWER:
            if (
                self.reason is not ChatReasonCode.ANSWER_ELIGIBLE
                or not self.provider_allowed
                or self.fixed_text is not None
            ):
                raise ValueError("invalid answer policy decision")
        elif self.outcome is ChatOutcome.CLARIFICATION:
            if (
                self.reason is not ChatReasonCode.NO_RESULTS
                or self.provider_allowed
                or self.fixed_text is None
            ):
                raise ValueError("invalid clarification policy decision")
        elif (
            self.reason not in _REFUSAL_REASONS or self.provider_allowed or self.fixed_text is None
        ):
            raise ValueError("invalid refusal policy decision")
        return self


class GroundedChatResult(_FrozenChatModel):
    """Final server-owned chat result with citations only for grounded answers."""

    outcome: ChatOutcome
    reason: ChatReasonCode
    answer: str = Field(max_length=ANSWER_MAX_CHARS)
    retrieval_run_id: UUID | None = None
    citations: tuple[ResolvedCitation, ...] = Field(default=(), max_length=MAX_CITATIONS)
    provider: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=128)

    @field_validator("answer", mode="before")
    @classmethod
    def normalize_result_answer(cls, value: object) -> object:
        return _normalized_nonblank(value, field_name="answer")

    _validate_provider_request_id = field_validator("provider_request_id")(
        _strict_optional_request_id
    )

    @model_validator(mode="after")
    def validate_result_route(self) -> "GroundedChatResult":
        citation_ids = tuple(citation.citation_id for citation in self.citations)
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("result citation IDs must be unique")
        if self.retrieval_run_id is not None and any(
            citation.retrieval_run_id != self.retrieval_run_id for citation in self.citations
        ):
            raise ValueError("result citations must match the retrieval run")

        provider_metadata_present = (
            self.provider is not None
            or self.model is not None
            or self.provider_request_id is not None
        )
        if self.outcome is ChatOutcome.ANSWER:
            if (
                self.reason is not ChatReasonCode.ANSWER_GROUNDED
                or self.retrieval_run_id is None
                or not self.citations
                or self.provider is None
                or self.model is None
            ):
                raise ValueError("invalid answer result")
        elif self.outcome is ChatOutcome.CLARIFICATION:
            if (
                self.reason is not ChatReasonCode.NO_RESULTS
                or self.retrieval_run_id is None
                or self.citations
                or provider_metadata_present
            ):
                raise ValueError("invalid clarification result")
        elif (
            self.reason not in _REFUSAL_REASONS
            or self.citations
            or provider_metadata_present
            or (
                self.reason is not ChatReasonCode.RETRIEVAL_FAILURE
                and self.retrieval_run_id is None
            )
        ):
            raise ValueError("invalid refusal result")
        return self
