"""Repository-contract coverage for M07 Phase 2 without persistence dependencies."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.chat import ChatOutcome, ChatReasonCode
from legal_chatbot.conversation import (
    ConversationCompactionCandidate,
    ConversationCompactionPlan,
    ConversationExchangeStatus,
    ConversationReference,
    ConversationReferenceKind,
    ConversationReservation,
    ConversationReservationResult,
    ConversationReservationStatus,
    ConversationStateSnapshot,
    ConversationStateUpdate,
    PersistedConversationExchange,
)


def _reference(kind: ConversationReferenceKind, ordinal: int) -> ConversationReference:
    return ConversationReference(kind=kind, reference_id=uuid4(), ordinal=ordinal)


def _answer_exchange(**changes: object) -> PersistedConversationExchange:
    values: dict[str, object] = {
        "conversation_id": uuid4(),
        "exchange_id": uuid4(),
        "ordinal": 1,
        "status": ConversationExchangeStatus.COMPLETED,
        "assistant_text": "Grounded answer",
        "chat_outcome": ChatOutcome.ANSWER,
        "chat_reason": ChatReasonCode.ANSWER_GROUNDED,
        "retrieval_run_id": uuid4(),
        "provider": "provider",
        "model": "model",
        "provider_request_id": "request-1",
        "references": (_reference(ConversationReferenceKind.CITATION, 0),),
    }
    values.update(changes)
    return PersistedConversationExchange.model_validate(values)


def _reservation() -> ConversationReservation:
    return ConversationReservation(
        conversation_id=uuid4(),
        exchange_id=uuid4(),
        ordinal=1,
        expected_state_version=0,
        snapshot=ConversationStateSnapshot(state_version=0),
    )


def test_persisted_answer_retains_only_ordered_reference_id_pointers() -> None:
    citation_first = _reference(ConversationReferenceKind.CITATION, 0)
    citation_second = _reference(ConversationReferenceKind.CITATION, 1)
    document = _reference(ConversationReferenceKind.DOCUMENT, 0)
    exchange = _answer_exchange(references=(citation_first, citation_second, document))

    assert exchange.citation_ids == (citation_first.reference_id, citation_second.reference_id)
    assert exchange.document_ids == (document.reference_id,)
    assert "delivery_id" not in type(exchange).model_fields
    assert "delivery_key_sha256" not in type(exchange).model_fields


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"status": ConversationExchangeStatus.PROCESSING}, "status"),
        ({"chat_reason": ChatReasonCode.NO_RESULTS}, "answer"),
        ({"retrieval_run_id": None}, "answer"),
        ({"provider": None}, "answer"),
        ({"model": None}, "answer"),
        ({"references": ()}, "answer"),
    ],
)
def test_persisted_answer_requires_completed_m06_provider_run_and_citation_shape(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _answer_exchange(**changes)


def test_persisted_clarification_and_refusal_follow_m06_outcome_matrix() -> None:
    clarification = PersistedConversationExchange(
        conversation_id=uuid4(),
        exchange_id=uuid4(),
        ordinal=1,
        status=ConversationExchangeStatus.COMPLETED,
        assistant_text="Please clarify.",
        chat_outcome=ChatOutcome.CLARIFICATION,
        chat_reason=ChatReasonCode.NO_RESULTS,
        retrieval_run_id=uuid4(),
    )
    retrieval_failure = PersistedConversationExchange(
        conversation_id=uuid4(),
        exchange_id=uuid4(),
        ordinal=1,
        status=ConversationExchangeStatus.COMPLETED,
        assistant_text="Unable to retrieve evidence.",
        chat_outcome=ChatOutcome.REFUSAL,
        chat_reason=ChatReasonCode.RETRIEVAL_FAILURE,
    )
    grounded_refusal = PersistedConversationExchange(
        conversation_id=uuid4(),
        exchange_id=uuid4(),
        ordinal=1,
        status=ConversationExchangeStatus.COMPLETED,
        assistant_text="Unable to answer safely.",
        chat_outcome=ChatOutcome.REFUSAL,
        chat_reason=ChatReasonCode.GROUNDING_FAILURE,
        retrieval_run_id=uuid4(),
    )

    assert clarification.references == ()
    assert retrieval_failure.retrieval_run_id is None
    assert grounded_refusal.retrieval_run_id is not None
    with pytest.raises(ValidationError, match="clarification"):
        PersistedConversationExchange(
            conversation_id=uuid4(),
            exchange_id=uuid4(),
            ordinal=1,
            status=ConversationExchangeStatus.COMPLETED,
            assistant_text="Please clarify.",
            chat_outcome=ChatOutcome.CLARIFICATION,
            chat_reason=ChatReasonCode.NO_RESULTS,
        )
    with pytest.raises(ValidationError, match="refusal"):
        PersistedConversationExchange(
            conversation_id=uuid4(),
            exchange_id=uuid4(),
            ordinal=1,
            status=ConversationExchangeStatus.COMPLETED,
            assistant_text="Unable to answer safely.",
            chat_outcome=ChatOutcome.REFUSAL,
            chat_reason=ChatReasonCode.GROUNDING_FAILURE,
        )


def test_persisted_references_are_ordered_and_deduplicated_by_both_schema_keys() -> None:
    citation = _reference(ConversationReferenceKind.CITATION, 0)
    with pytest.raises(ValidationError, match="ordered"):
        _answer_exchange(
            references=(_reference(ConversationReferenceKind.DOCUMENT, 0), citation),
        )
    with pytest.raises(ValidationError, match="identity"):
        _answer_exchange(
            references=(
                citation,
                ConversationReference(
                    kind=ConversationReferenceKind.CITATION,
                    reference_id=citation.reference_id,
                    ordinal=1,
                ),
            )
        )
    with pytest.raises(ValidationError, match="ordinal"):
        _answer_exchange(references=(citation, _reference(ConversationReferenceKind.CITATION, 0)))
    with pytest.raises(ValidationError, match="refusal"):
        PersistedConversationExchange(
            conversation_id=uuid4(),
            exchange_id=uuid4(),
            ordinal=1,
            status=ConversationExchangeStatus.COMPLETED,
            assistant_text="Unable to retrieve evidence.",
            chat_outcome=ChatOutcome.REFUSAL,
            chat_reason=ChatReasonCode.RETRIEVAL_FAILURE,
            references=(_reference(ConversationReferenceKind.DOCUMENT, 0),),
        )


def test_reservation_result_shapes_and_state_updates_are_bounded_frozen_and_non_echoing() -> None:
    reservation = _reservation()
    completed = _answer_exchange()

    assert (
        ConversationReservationResult(
            status=ConversationReservationStatus.RESERVED, reservation=reservation
        ).reservation
        == reservation
    )
    assert (
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_COMPLETED, completed=completed
        ).completed
        == completed
    )
    assert (
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_PROCESSING,
            conversation_id=reservation.conversation_id,
            exchange_id=reservation.exchange_id,
        ).exchange_id
        == reservation.exchange_id
    )
    assert (
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_TERMINAL,
            conversation_id=reservation.conversation_id,
            exchange_id=reservation.exchange_id,
        ).conversation_id
        == reservation.conversation_id
    )
    with pytest.raises(ValidationError, match="requires"):
        ConversationReservationResult(status=ConversationReservationStatus.RESERVED)
    with pytest.raises(ValidationError, match="require only identity"):
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_PROCESSING,
            reservation=reservation,
            conversation_id=reservation.conversation_id,
            exchange_id=reservation.exchange_id,
        )
    with pytest.raises(ValidationError, match="require only identity"):
        ConversationReservationResult(status=ConversationReservationStatus.DUPLICATE_TERMINAL)
    with pytest.raises(ValidationError, match="requires only"):
        ConversationReservationResult(
            status=ConversationReservationStatus.RESERVED,
            reservation=reservation,
            conversation_id=reservation.conversation_id,
        )

    update = ConversationStateUpdate(
        expected_state_version=0,
        rolling_summary="  ca\u0300 phe\u0302  ",
        active_topic="  topic  ",
    )
    assert update.rolling_summary == "cà phê"
    assert update.active_topic == "topic"
    with pytest.raises(ValidationError) as error:
        ConversationStateUpdate(expected_state_version=0, rolling_summary="UPDATE_SENTINEL\x00")
    assert "UPDATE_SENTINEL" not in str(error.value)
    with pytest.raises(ValidationError):
        update.active_topic = "changed"  # type: ignore[misc]


def test_compaction_contracts_require_terminal_shapes_and_exact_ordered_ids() -> None:
    completed = ConversationCompactionCandidate(
        exchange_id=uuid4(),
        ordinal=1,
        status=ConversationExchangeStatus.COMPLETED,
        user_text="Question",
        assistant_text="Answer",
        chat_outcome=ChatOutcome.CLARIFICATION,
        chat_reason="NO_RESULTS",
        citation_count=0,
        document_count=0,
    )
    abandoned = ConversationCompactionCandidate(
        exchange_id=uuid4(),
        ordinal=2,
        status=ConversationExchangeStatus.ABANDONED,
        user_text="Question",
        chat_reason="LEASE_EXPIRED",
        citation_count=0,
        document_count=0,
    )
    plan = ConversationCompactionPlan(
        exchange_ids=(completed.exchange_id, abandoned.exchange_id),
        candidates=(completed, abandoned),
    )

    assert _reservation().compaction_plan == ConversationCompactionPlan()
    assert plan.exchange_ids == (completed.exchange_id, abandoned.exchange_id)
    with pytest.raises(ValidationError, match="terminal"):
        ConversationCompactionCandidate(
            exchange_id=uuid4(),
            ordinal=1,
            status=ConversationExchangeStatus.PROCESSING,
            user_text="Question",
            citation_count=0,
            document_count=0,
        )
    with pytest.raises(ValidationError, match="incomplete"):
        ConversationCompactionCandidate(
            exchange_id=uuid4(),
            ordinal=1,
            status=ConversationExchangeStatus.COMPLETED,
            user_text="Question",
            citation_count=0,
            document_count=0,
        )
    with pytest.raises(ValidationError, match="match in order"):
        ConversationCompactionPlan(
            exchange_ids=(completed.exchange_id,), candidates=(completed, abandoned)
        )
    with pytest.raises(ValidationError, match="unique"):
        ConversationStateUpdate(
            expected_state_version=0,
            compacted_exchange_ids=(completed.exchange_id, completed.exchange_id),
        )
