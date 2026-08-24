"""Focused immutable-contract coverage for M07 Phase 1 conversation contracts."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.chat import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.conversation import (
    ACTIVE_TOPIC_MAX_CHARS,
    DELIVERY_ID_MAX_CHARS,
    REFERENCE_LIMIT_PER_KIND,
    ROLLING_SUMMARY_MAX_CHARS,
    USER_TEXT_MAX_CHARS,
    ConversationExchangeStatus,
    ConversationReference,
    ConversationReferenceKind,
    ConversationRequest,
    ConversationResult,
    ConversationStateSnapshot,
    ConversationTurn,
    ConversationTurnRole,
    CreateConversationResult,
)
from legal_chatbot.retrieval import TemporalScope


def _turn(ordinal: int, role: ConversationTurnRole = ConversationTurnRole.USER) -> ConversationTurn:
    if role is ConversationTurnRole.USER:
        return ConversationTurn(ordinal=ordinal, role=role, text="user")
    return ConversationTurn(
        ordinal=ordinal,
        role=role,
        text="assistant",
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
    )


def _chat() -> GroundedChatResult:
    return GroundedChatResult(
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
        answer="Please clarify the document or issue.",
        retrieval_run_id=uuid4(),
    )


def test_request_and_create_result_are_nfc_normalized_bounded_and_immutable() -> None:
    conversation_id = uuid4()
    request = ConversationRequest(
        conversation_id=conversation_id,
        delivery_id="  ca\u0300 phe\u0302  ",
        text="  question  ",
        temporal_scope=TemporalScope.NONE,
    )

    assert (
        CreateConversationResult(conversation_id=conversation_id).conversation_id == conversation_id
    )
    assert request.delivery_id == "cà phê"
    assert request.text == "question"
    with pytest.raises(ValidationError, match="invalid"):
        ConversationRequest(conversation_id=conversation_id, delivery_id="\x00", text="question")
    with pytest.raises(ValidationError):
        ConversationRequest(
            conversation_id=conversation_id,
            delivery_id="d" * (DELIVERY_ID_MAX_CHARS + 1),
            text="question",
        )
    with pytest.raises(ValidationError):
        ConversationRequest(
            conversation_id=conversation_id, delivery_id="delivery", text="x" * 4_001
        )
    with pytest.raises(ValidationError):
        request.text = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ConversationRequest.model_validate(
            {
                "conversation_id": conversation_id,
                "delivery_id": "delivery",
                "text": "question",
                "extra": 1,
            }
        )


def test_turns_require_role_appropriate_chat_outcome_and_reason() -> None:
    assert _turn(1).outcome is None
    assert _turn(2, ConversationTurnRole.ASSISTANT).reason is ChatReasonCode.NO_RESULTS
    with pytest.raises(ValidationError, match="user turn"):
        ConversationTurn(
            ordinal=1,
            role=ConversationTurnRole.USER,
            text="user",
            outcome=ChatOutcome.CLARIFICATION,
        )
    with pytest.raises(ValidationError, match="requires"):
        ConversationTurn(ordinal=1, role=ConversationTurnRole.ASSISTANT, text="assistant")
    with pytest.raises(ValidationError, match="invalid"):
        ConversationTurn(
            ordinal=1,
            role=ConversationTurnRole.ASSISTANT,
            text="assistant",
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.NO_RESULTS,
        )


def test_snapshot_enforces_turn_and_reference_bounds_without_echoing_input() -> None:
    references = tuple(
        ConversationReference(
            kind=ConversationReferenceKind.CITATION,
            reference_id=uuid4(),
            ordinal=index,
        )
        for index in range(REFERENCE_LIMIT_PER_KIND)
    )
    snapshot = ConversationStateSnapshot(
        state_version=0,
        rolling_summary="summary",
        active_topic="topic",
        recent_turns=(_turn(1), _turn(2, ConversationTurnRole.ASSISTANT)),
        references=references,
    )

    assert len(snapshot.references) == REFERENCE_LIMIT_PER_KIND
    with pytest.raises(ValidationError, match="ordinals"):
        ConversationStateSnapshot(state_version=0, recent_turns=(_turn(2), _turn(1)))
    duplicate_id = uuid4()
    with pytest.raises(ValidationError, match="unique"):
        ConversationStateSnapshot(
            state_version=0,
            references=(
                ConversationReference(
                    kind=ConversationReferenceKind.DOCUMENT, reference_id=duplicate_id, ordinal=0
                ),
                ConversationReference(
                    kind=ConversationReferenceKind.DOCUMENT, reference_id=duplicate_id, ordinal=1
                ),
            ),
        )
    with pytest.raises(ValidationError, match="kind and ordinal"):
        ConversationStateSnapshot(
            state_version=0,
            references=(
                ConversationReference(
                    kind=ConversationReferenceKind.DOCUMENT, reference_id=uuid4(), ordinal=0
                ),
                ConversationReference(
                    kind=ConversationReferenceKind.DOCUMENT, reference_id=uuid4(), ordinal=0
                ),
            ),
        )
    sentinel = "SUMMARY_SENTINEL_DO_NOT_ECHO"
    with pytest.raises(ValidationError) as error:
        ConversationStateSnapshot(
            state_version=0, rolling_summary=sentinel + "x" * ROLLING_SUMMARY_MAX_CHARS
        )
    assert sentinel not in str(error.value)
    with pytest.raises(ValidationError):
        ConversationStateSnapshot(state_version=0, active_topic="x" * (ACTIVE_TOPIC_MAX_CHARS + 1))
    with pytest.raises(ValidationError):
        ConversationReference(
            kind=ConversationReferenceKind.CITATION, reference_id=uuid4(), ordinal=6
        )


def test_result_lifecycle_requires_chat_only_for_completed_and_allows_pending_replay() -> None:
    conversation_id = uuid4()
    exchange_id = uuid4()
    assert (
        ConversationResult(
            conversation_id=conversation_id,
            exchange_id=exchange_id,
            status=ConversationExchangeStatus.COMPLETED,
            duplicate=True,
            chat=_chat(),
        ).chat
        is not None
    )
    assert (
        ConversationResult(
            conversation_id=conversation_id,
            exchange_id=exchange_id,
            status=ConversationExchangeStatus.PROCESSING,
            duplicate=True,
        ).chat
        is None
    )
    with pytest.raises(ValidationError, match="requires chat"):
        ConversationResult(
            conversation_id=conversation_id,
            exchange_id=exchange_id,
            status=ConversationExchangeStatus.COMPLETED,
            duplicate=False,
        )
    with pytest.raises(ValidationError, match="must not include"):
        ConversationResult(
            conversation_id=conversation_id,
            exchange_id=exchange_id,
            status=ConversationExchangeStatus.FAILED,
            duplicate=False,
            chat=_chat(),
        )
    with pytest.raises(ValidationError, match="duplicate"):
        ConversationResult(
            conversation_id=conversation_id,
            exchange_id=exchange_id,
            status=ConversationExchangeStatus.ABANDONED,
            duplicate=True,
        )


def test_model_maxima_are_synchronized_with_the_persistence_contract() -> None:
    assert USER_TEXT_MAX_CHARS == 4_000
    assert DELIVERY_ID_MAX_CHARS == 256
    assert REFERENCE_LIMIT_PER_KIND == 6
