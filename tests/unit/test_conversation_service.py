"""Deterministic M07 Phase 3 conversation service coverage with narrow fake ports."""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from legal_chatbot.chat import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.conversation import (
    ConversationError,
    ConversationErrorCode,
    ConversationExchangeStatus,
    ConversationReference,
    ConversationReferenceKind,
    ConversationRequest,
    ConversationReservation,
    ConversationReservationResult,
    ConversationReservationStatus,
    ConversationSettings,
    ConversationStateSnapshot,
    ConversationStateUpdate,
    ConversationTurn,
    ConversationTurnRole,
    PersistedConversationExchange,
)
from legal_chatbot.conversation.service import ConversationService
from legal_chatbot.retrieval import ResolvedCitation

NOW = datetime(2026, 8, 20, tzinfo=UTC)


def _request(conversation_id: UUID | None = None) -> ConversationRequest:
    return ConversationRequest(
        conversation_id=conversation_id or uuid4(),
        delivery_id="delivery",
        text="CURRENT_QUESTION_SENTINEL",
    )


def _reservation(request: ConversationRequest) -> ConversationReservation:
    return ConversationReservation(
        conversation_id=request.conversation_id,
        exchange_id=uuid4(),
        ordinal=2,
        expected_state_version=3,
        snapshot=ConversationStateSnapshot(
            state_version=3,
            rolling_summary="PRIOR_SUMMARY_SENTINEL",
            active_topic="prior topic",
            recent_turns=(
                ConversationTurn(ordinal=1, role=ConversationTurnRole.USER, text="old question"),
            ),
        ),
    )


def _citation(citation_id: UUID, run_id: UUID, document_id: UUID) -> ResolvedCitation:
    return ResolvedCitation(
        citation_id=citation_id,
        retrieval_run_id=run_id,
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=document_id,
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="123",
    )


def _persisted(
    *,
    outcome: ChatOutcome = ChatOutcome.CLARIFICATION,
    reason: ChatReasonCode = ChatReasonCode.NO_RESULTS,
    run_id: UUID | None = None,
    references: tuple[ConversationReference, ...] = (),
) -> PersistedConversationExchange:
    run_id = run_id or uuid4()
    values: dict[str, object] = {
        "conversation_id": uuid4(),
        "exchange_id": uuid4(),
        "ordinal": 1,
        "status": ConversationExchangeStatus.COMPLETED,
        "assistant_text": "PERSISTED_ANSWER_SENTINEL",
        "chat_outcome": outcome,
        "chat_reason": reason,
        "retrieval_run_id": run_id,
        "references": references,
    }
    if outcome is ChatOutcome.ANSWER:
        values.update(provider="provider", model="model", provider_request_id="request-1")
    if outcome is ChatOutcome.REFUSAL and reason is ChatReasonCode.RETRIEVAL_FAILURE:
        values["retrieval_run_id"] = run_id
    return PersistedConversationExchange.model_validate(values)


class _Repository:
    def __init__(
        self,
        reservation_result: ConversationReservationResult,
        completed: PersistedConversationExchange,
    ):
        self.reservation_result = reservation_result
        self.completed = completed
        self.reserve_calls = 0
        self.reserve_error: ConversationError | None = None
        self.complete_calls: list[tuple[object, ...]] = []
        self.complete_error: ConversationError | None = None

    async def create_conversation(self, now):
        raise AssertionError("not used")

    async def reserve(self, request, now):
        self.reserve_calls += 1
        if self.reserve_error is not None:
            raise self.reserve_error
        return self.reservation_result

    async def load_snapshot(self, conversation_id, now):
        raise AssertionError("not used")

    async def complete(self, reservation, chat, state_update, now):
        self.complete_calls.append((reservation, chat, state_update, now))
        if self.complete_error is not None:
            raise self.complete_error
        return self.completed

    async def purge_expired(self, now, limit):
        raise AssertionError("not used")


class _Chat:
    def __init__(self, result: GroundedChatResult | Exception):
        self.result = result
        self.requests = []

    async def respond(self, request):
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _Resolver:
    def __init__(self, values: dict[UUID, ResolvedCitation | Exception]):
        self.values = values
        self.calls: list[tuple[UUID, UUID]] = []

    async def resolve(self, citation_id, expected_retrieval_run_id):
        self.calls.append((citation_id, expected_retrieval_run_id))
        value = self.values[citation_id]
        if isinstance(value, Exception):
            raise value
        return value


def _service(repository, chat, resolver) -> ConversationService:
    return ConversationService(
        repository, chat, resolver, ConversationSettings(context_max_chars=100)
    )


async def test_reserved_delivery_builds_separated_context_and_completes_once() -> None:
    request = _request()
    reservation = _reservation(request)
    chat_result = GroundedChatResult(
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
        answer="Please clarify.",
        retrieval_run_id=uuid4(),
    )
    persisted = _persisted(run_id=chat_result.retrieval_run_id)
    repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.RESERVED, reservation=reservation
        ),
        persisted,
    )
    chat = _Chat(chat_result)
    resolver = _Resolver({})

    result = await _service(repository, chat, resolver).respond(request, NOW)

    assert result.duplicate is False
    assert result.chat == chat_result
    assert len(chat.requests) == 1
    assert chat.requests[0].question == request.text
    assert chat.requests[0].retrieval_query == f"{request.text}\nActive topic: prior topic"
    assert chat.requests[0].conversation_context is not None
    assert "CURRENT_QUESTION_SENTINEL" not in str(chat.requests[0].conversation_context)
    assert len(repository.complete_calls) == 1
    state_update = cast(ConversationStateUpdate, repository.complete_calls[0][2])
    assert state_update.expected_state_version == reservation.expected_state_version
    assert state_update.active_topic == request.text[:256]


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (ChatOutcome.CLARIFICATION, ChatReasonCode.NO_RESULTS),
        (ChatOutcome.REFUSAL, ChatReasonCode.GROUNDING_FAILURE),
    ],
)
async def test_duplicate_completed_non_answers_bypass_chat_and_resolver(outcome, reason) -> None:
    persisted = _persisted(outcome=outcome, reason=reason)
    if outcome is ChatOutcome.REFUSAL:
        persisted = _persisted(outcome=outcome, reason=reason, run_id=uuid4())
    request = _request(persisted.conversation_id)
    repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_COMPLETED, completed=persisted
        ),
        persisted,
    )
    chat = _Chat(AssertionError("must not call"))
    resolver = _Resolver({})

    result = await _service(repository, chat, resolver).respond(request, NOW)

    assert result.duplicate is True
    assert result.chat is not None and result.chat.outcome is outcome
    assert not chat.requests
    assert not resolver.calls
    assert not repository.complete_calls


async def test_duplicate_completed_answer_reresolves_ordered_citations_and_documents() -> None:
    run_id = uuid4()
    first_id, second_id = uuid4(), uuid4()
    first_document, second_document = uuid4(), uuid4()
    references = (
        ConversationReference(
            kind=ConversationReferenceKind.CITATION, reference_id=first_id, ordinal=0
        ),
        ConversationReference(
            kind=ConversationReferenceKind.CITATION, reference_id=second_id, ordinal=1
        ),
        ConversationReference(
            kind=ConversationReferenceKind.DOCUMENT, reference_id=first_document, ordinal=0
        ),
        ConversationReference(
            kind=ConversationReferenceKind.DOCUMENT, reference_id=second_document, ordinal=1
        ),
    )
    persisted = _persisted(
        outcome=ChatOutcome.ANSWER,
        reason=ChatReasonCode.ANSWER_GROUNDED,
        run_id=run_id,
        references=references,
    )
    request = _request(persisted.conversation_id)
    repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_COMPLETED, completed=persisted
        ),
        persisted,
    )
    resolver = _Resolver(
        {
            first_id: _citation(first_id, run_id, first_document),
            second_id: _citation(second_id, run_id, second_document),
        }
    )

    result = await _service(repository, _Chat(AssertionError("must not call")), resolver).respond(
        request, NOW
    )

    assert result.chat is not None
    assert tuple(citation.citation_id for citation in result.chat.citations) == (
        first_id,
        second_id,
    )
    assert resolver.calls == [(first_id, run_id), (second_id, run_id)]
    assert not repository.complete_calls


@pytest.mark.parametrize("mismatch", ["resolver", "identity", "documents"])
async def test_duplicate_answer_revalidation_failures_return_fixed_refusal_without_mutation(
    mismatch,
) -> None:
    run_id, citation_id, document_id = uuid4(), uuid4(), uuid4()
    references = (
        ConversationReference(
            kind=ConversationReferenceKind.CITATION, reference_id=citation_id, ordinal=0
        ),
        ConversationReference(
            kind=ConversationReferenceKind.DOCUMENT, reference_id=document_id, ordinal=0
        ),
    )
    persisted = _persisted(
        outcome=ChatOutcome.ANSWER,
        reason=ChatReasonCode.ANSWER_GROUNDED,
        run_id=run_id,
        references=references,
    )
    request = _request(persisted.conversation_id)
    value: ResolvedCitation | Exception
    if mismatch == "resolver":
        value = RuntimeError("RESOLVER_SENTINEL")
    elif mismatch == "identity":
        value = _citation(uuid4(), run_id, document_id)
    else:
        value = _citation(citation_id, run_id, uuid4())
    repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_COMPLETED, completed=persisted
        ),
        persisted,
    )

    result = await _service(
        repository, _Chat(AssertionError("must not call")), _Resolver({citation_id: value})
    ).respond(request, NOW)

    assert result.duplicate is True
    assert result.chat is not None
    assert result.chat.reason is ChatReasonCode.CITATION_REVALIDATION_FAILURE
    assert result.chat.citations == ()
    assert not repository.complete_calls


async def test_duplicate_completed_from_another_conversation_fails_closed_without_replay() -> None:
    persisted = _persisted()
    repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_COMPLETED, completed=persisted
        ),
        persisted,
    )
    chat = _Chat(AssertionError("must not call"))
    resolver = _Resolver({})
    service = _service(repository, chat, resolver)
    records = []

    class _Logger:
        def info(self, event, *, extra):
            records.append((event, extra))

    service._logger = cast(Any, _Logger())
    with pytest.raises(ConversationError) as error:
        await service.respond(_request(), NOW)

    assert error.value.code is ConversationErrorCode.PERSISTENCE_FAILURE
    assert not chat.requests
    assert not resolver.calls
    assert not repository.complete_calls
    assert "PERSISTED_ANSWER_SENTINEL" not in str(error.value)
    assert "PERSISTED_ANSWER_SENTINEL" not in str(records)


async def test_processing_terminal_busy_and_completion_conflict_do_not_retry_chat() -> None:
    processing_request = _request()
    processing_exchange_id = uuid4()
    processing_repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_PROCESSING,
            conversation_id=processing_request.conversation_id,
            exchange_id=processing_exchange_id,
        ),
        _persisted(),
    )
    processing_chat = _Chat(AssertionError("must not call"))
    processing = await _service(processing_repository, processing_chat, _Resolver({})).respond(
        processing_request, NOW
    )
    assert processing.status is ConversationExchangeStatus.PROCESSING
    assert processing.conversation_id == processing_request.conversation_id
    assert processing.exchange_id == processing_exchange_id
    assert not processing_chat.requests

    busy_request = _request()
    busy_repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_PROCESSING,
            conversation_id=busy_request.conversation_id,
            exchange_id=uuid4(),
        ),
        _persisted(),
    )
    busy_repository.reserve_error = ConversationError(ConversationErrorCode.BUSY)
    busy_chat = _Chat(AssertionError("must not call"))
    with pytest.raises(ConversationError) as busy_error:
        await _service(busy_repository, busy_chat, _Resolver({})).respond(busy_request, NOW)
    assert busy_error.value.code is ConversationErrorCode.BUSY
    assert not busy_chat.requests

    terminal_request = _request()
    terminal_repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_TERMINAL,
            conversation_id=terminal_request.conversation_id,
            exchange_id=uuid4(),
        ),
        _persisted(),
    )
    with pytest.raises(ConversationError) as terminal_error:
        await _service(terminal_repository, _Chat(AssertionError()), _Resolver({})).respond(
            terminal_request, NOW
        )
    assert terminal_error.value.code is ConversationErrorCode.LEASE_EXPIRED

    request = _request()
    reservation = _reservation(request)
    chat_result = GroundedChatResult(
        outcome=ChatOutcome.CLARIFICATION,
        reason=ChatReasonCode.NO_RESULTS,
        answer="Please clarify.",
        retrieval_run_id=uuid4(),
    )
    conflict_repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.RESERVED, reservation=reservation
        ),
        _persisted(run_id=chat_result.retrieval_run_id),
    )

    conflict_repository.complete_error = ConversationError(ConversationErrorCode.CONFLICT)
    conflict_chat = _Chat(chat_result)
    with pytest.raises(ConversationError) as conflict_error:
        await _service(conflict_repository, conflict_chat, _Resolver({})).respond(request, NOW)
    assert conflict_error.value.code is ConversationErrorCode.CONFLICT
    assert len(conflict_chat.requests) == 1


@pytest.mark.parametrize(
    "status",
    [
        ConversationReservationStatus.DUPLICATE_PROCESSING,
        ConversationReservationStatus.DUPLICATE_TERMINAL,
    ],
)
async def test_duplicate_status_with_mismatched_conversation_pointer_fails_closed_without_m06(
    status: ConversationReservationStatus,
) -> None:
    request = _request()
    repository = _Repository(
        ConversationReservationResult(
            status=status,
            conversation_id=uuid4(),
            exchange_id=uuid4(),
        ),
        _persisted(),
    )
    chat = _Chat(AssertionError("must not call"))

    with pytest.raises(ConversationError) as error:
        await _service(repository, chat, _Resolver({})).respond(request, NOW)

    assert error.value.code is ConversationErrorCode.PERSISTENCE_FAILURE
    assert not chat.requests
    assert not repository.complete_calls


async def test_chat_exception_is_synthesized_and_persisted_without_content_logging() -> None:
    request = _request()
    reservation = _reservation(request)
    persisted = _persisted(
        outcome=ChatOutcome.REFUSAL,
        reason=ChatReasonCode.RETRIEVAL_FAILURE,
        run_id=None,
    )
    repository = _Repository(
        ConversationReservationResult(
            status=ConversationReservationStatus.RESERVED, reservation=reservation
        ),
        persisted,
    )
    service = _service(repository, _Chat(RuntimeError("CHAT_SENTINEL")), _Resolver({}))
    records = []

    class _Logger:
        def info(self, event, *, extra):
            records.append((event, extra))

    service._logger = cast(Any, _Logger())
    result = await service.respond(request, NOW)

    assert result.chat is not None
    assert result.chat.reason is ChatReasonCode.RETRIEVAL_FAILURE
    completed_chat = cast(GroundedChatResult, repository.complete_calls[0][1])
    assert completed_chat.reason is ChatReasonCode.RETRIEVAL_FAILURE
    rendered = str(records)
    assert "CURRENT_QUESTION_SENTINEL" not in rendered
    assert "PRIOR_SUMMARY_SENTINEL" not in rendered
    assert "CHAT_SENTINEL" not in rendered
