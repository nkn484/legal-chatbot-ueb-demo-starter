"""Pure mapping coverage for the M07 PostgreSQL repository."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import (
    ConversationReservation,
    ConversationStateSnapshot,
    ConversationStateUpdate,
)
from legal_chatbot.conversation.orm import ConversationExchange
from legal_chatbot.conversation.repository import (
    PostgresConversationRepository,
    _compaction_candidate,
    _conversation_error_for_unexpected,
    _derived_references,
    _is_postgresql_unique_violation,
    _repository_now,
)
from legal_chatbot.retrieval.models import ResolvedCitation


class _NoSessionFactory:
    def __call__(self):
        raise AssertionError("database access is not expected")


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate


def _citation(*, document_id=None) -> ResolvedCitation:
    return ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=document_id or uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="TEST",
        external_id="test",
    )


def _answer() -> GroundedChatResult:
    document_id = uuid4()
    first = _citation(document_id=document_id)
    second = _citation(document_id=document_id)
    return GroundedChatResult(
        outcome=ChatOutcome.ANSWER,
        reason=ChatReasonCode.ANSWER_GROUNDED,
        answer="Grounded answer.",
        retrieval_run_id=first.retrieval_run_id,
        citations=(
            first,
            second.model_copy(update={"retrieval_run_id": first.retrieval_run_id}),
        ),
        provider="test-provider",
        model="test-model",
    )


def test_derived_answer_references_preserve_citation_order_and_deduplicate_documents() -> None:
    answer = _answer()

    references = _derived_references(answer)

    assert [(reference.kind.value, reference.ordinal) for reference in references] == [
        ("CITATION", 0),
        ("CITATION", 1),
        ("DOCUMENT", 0),
    ]
    assert tuple(reference.reference_id for reference in references[:2]) == tuple(
        citation.citation_id for citation in answer.citations
    )
    assert references[2].reference_id == answer.citations[0].document_id


@pytest.mark.parametrize(
    ("outcome", "reason", "answer"),
    [
        (ChatOutcome.CLARIFICATION, ChatReasonCode.NO_RESULTS, "Please clarify."),
        (ChatOutcome.REFUSAL, ChatReasonCode.RETRIEVAL_FAILURE, "Unable to retrieve evidence."),
    ],
)
def test_non_answer_results_never_derive_references(
    outcome: ChatOutcome, reason: ChatReasonCode, answer: str
) -> None:
    chat = GroundedChatResult(
        outcome=outcome,
        reason=reason,
        answer=answer,
        retrieval_run_id=uuid4() if outcome is ChatOutcome.CLARIFICATION else None,
    )

    assert _derived_references(chat) == ()


@pytest.mark.asyncio
async def test_invalid_chat_is_rejected_before_database_access() -> None:
    repository = PostgresConversationRepository(_NoSessionFactory(), ConversationSettings())  # type: ignore[arg-type]
    reservation = ConversationReservation(
        conversation_id=uuid4(),
        exchange_id=uuid4(),
        ordinal=1,
        expected_state_version=0,
        snapshot=ConversationStateSnapshot(state_version=0),
    )

    with pytest.raises(ConversationError) as error:
        await repository.complete(
            reservation,
            object(),  # type: ignore[arg-type]
            ConversationStateUpdate(expected_state_version=0),
            datetime.now(UTC),
        )

    assert error.value.code is ConversationErrorCode.STATE_INVALID


def test_repository_clock_and_unexpected_error_normalization_are_code_only() -> None:
    assert _repository_now(datetime(2026, 8, 20, tzinfo=UTC)) == datetime(2026, 8, 20, tzinfo=UTC)
    with pytest.raises(ConversationError) as clock_error:
        _repository_now(datetime(2026, 8, 20))
    assert clock_error.value.code is ConversationErrorCode.STATE_INVALID

    known = ConversationError(ConversationErrorCode.CONFLICT)
    assert _conversation_error_for_unexpected(known) is known
    assert _conversation_error_for_unexpected(RuntimeError("private database text")).code is (
        ConversationErrorCode.PERSISTENCE_FAILURE
    )
    assert (
        str(_conversation_error_for_unexpected(ValueError("private input text"))) == "STATE_INVALID"
    )


def test_postgresql_unique_violation_detection_is_narrow() -> None:
    unique = IntegrityError(None, None, _DriverError("23505"))
    non_unique = IntegrityError(None, None, _DriverError("23503"))

    assert _is_postgresql_unique_violation(unique)
    assert not _is_postgresql_unique_violation(non_unique)


def test_compaction_candidate_mapping_preserves_terminal_shape_and_reference_counts() -> None:
    exchange = ConversationExchange(
        id=uuid4(),
        conversation_id=uuid4(),
        delivery_key_sha256="0" * 64,
        ordinal=4,
        status="COMPLETED",
        user_text="Question",
        assistant_text="Answer",
        chat_outcome="CLARIFICATION",
        chat_reason="NO_RESULTS",
    )

    candidate = _compaction_candidate(exchange, citation_count=2, document_count=1)

    assert candidate.exchange_id == exchange.id
    assert candidate.ordinal == 4
    assert candidate.citation_count == 2
    assert candidate.document_count == 1
