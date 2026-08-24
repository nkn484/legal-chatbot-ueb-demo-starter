"""Deterministic conversation orchestration over bounded repository and chat ports."""

from datetime import datetime
from time import perf_counter
from typing import Any, TypeVar
from uuid import UUID

from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.chat.policy import refusal_decision
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import (
    ConversationExchangeStatus,
    ConversationRequest,
    ConversationReservationResult,
    ConversationReservationStatus,
    ConversationResult,
    CreateConversationResult,
    PersistedConversationExchange,
)
from legal_chatbot.conversation.policy import build_chat_request, build_state_update
from legal_chatbot.conversation.port import ConversationRepositoryPort, GroundedChatPort
from legal_chatbot.core.logging import get_logger
from legal_chatbot.retrieval.models import ResolvedCitation
from legal_chatbot.retrieval.port import CitationResolverPort

_Model = TypeVar("_Model")


class ConversationService:
    """Coordinate one idempotent delivery without exposing persistence or channel details."""

    def __init__(
        self,
        repository: ConversationRepositoryPort,
        grounded_chat: GroundedChatPort,
        citation_resolver: CitationResolverPort,
        settings: object,
    ) -> None:
        self._repository = repository
        self._grounded_chat = grounded_chat
        self._citation_resolver = citation_resolver
        self._settings = settings
        self._logger = get_logger()

    async def create_conversation(self, now: datetime) -> CreateConversationResult:
        """Delegate one creation call and reject malformed port output without retrying."""

        try:
            value = await self._repository.create_conversation(now)
            return self._validated(value, CreateConversationResult)
        except ConversationError as error:
            self._log_repository_error(error, started_at=None)
            raise
        except Exception:
            self._log(
                "conversation_failed", error_code=ConversationErrorCode.PERSISTENCE_FAILURE.value
            )
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE) from None

    async def respond(self, request: ConversationRequest, now: datetime) -> ConversationResult:
        """Reserve once, process exactly once when owned, and safely replay completed results."""

        started_at = perf_counter()
        try:
            reservation_result = self._validated(
                await self._repository.reserve(request, now), ConversationReservationResult
            )
        except ConversationError as error:
            self._log_repository_error(error, started_at=started_at)
            raise
        except Exception:
            self._log(
                "conversation_failed",
                error_code=ConversationErrorCode.PERSISTENCE_FAILURE.value,
                duration_ms=self._duration_ms(started_at),
            )
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE) from None

        if reservation_result.status is ConversationReservationStatus.DUPLICATE_PROCESSING:
            conversation_id, exchange_id = self._duplicate_identity(reservation_result, request)
            self._log(
                "conversation_busy",
                status=ConversationExchangeStatus.PROCESSING.value,
                reason=ConversationErrorCode.IN_PROGRESS.value,
                duration_ms=self._duration_ms(started_at),
            )
            return ConversationResult(
                conversation_id=conversation_id,
                exchange_id=exchange_id,
                status=ConversationExchangeStatus.PROCESSING,
                duplicate=True,
            )
        if reservation_result.status is ConversationReservationStatus.DUPLICATE_TERMINAL:
            self._duplicate_identity(reservation_result, request)
            self._log(
                "conversation_expired",
                reason=ConversationErrorCode.LEASE_EXPIRED.value,
                error_code=ConversationErrorCode.LEASE_EXPIRED.value,
                duration_ms=self._duration_ms(started_at),
            )
            raise ConversationError(ConversationErrorCode.LEASE_EXPIRED)
        if reservation_result.status is ConversationReservationStatus.DUPLICATE_COMPLETED:
            return await self._replay_completed(reservation_result, request, started_at)

        reservation = reservation_result.reservation
        if reservation is None:
            self._log(
                "conversation_failed",
                error_code=ConversationErrorCode.PERSISTENCE_FAILURE.value,
                duration_ms=self._duration_ms(started_at),
            )
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE)
        self._log(
            "conversation_reserved",
            status=reservation_result.status.value,
            ordinal=reservation.ordinal,
            state_version=reservation.expected_state_version,
            recent_turn_count=len(reservation.snapshot.recent_turns),
            reference_count=len(reservation.snapshot.references),
            duration_ms=self._duration_ms(started_at),
        )

        try:
            chat = self._validated(
                await self._grounded_chat.respond(
                    build_chat_request(request, reservation, self._settings)
                ),
                GroundedChatResult,
            )
        except Exception:
            chat = self._fixed_refusal(ChatReasonCode.RETRIEVAL_FAILURE, None)

        try:
            state_update = build_state_update(reservation, request, self._settings)
            completed = self._validated(
                await self._repository.complete(reservation, chat, state_update, now),
                PersistedConversationExchange,
            )
        except ConversationError as error:
            self._log_repository_error(
                error,
                started_at=started_at,
                ordinal=reservation.ordinal,
                state_version=reservation.expected_state_version,
            )
            raise
        except Exception:
            self._log(
                "conversation_failed",
                ordinal=reservation.ordinal,
                state_version=reservation.expected_state_version,
                error_code=ConversationErrorCode.PERSISTENCE_FAILURE.value,
                duration_ms=self._duration_ms(started_at),
            )
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE) from None

        self._log(
            "conversation_completed",
            status=completed.status.value,
            reason=chat.reason.value,
            ordinal=completed.ordinal,
            state_version=reservation.expected_state_version,
            reference_count=len(completed.references),
            outcome=chat.outcome.value,
            duration_ms=self._duration_ms(started_at),
        )
        return ConversationResult(
            conversation_id=reservation.conversation_id,
            exchange_id=reservation.exchange_id,
            status=ConversationExchangeStatus.COMPLETED,
            duplicate=False,
            chat=chat,
        )

    async def _replay_completed(
        self,
        reservation_result: ConversationReservationResult,
        request: ConversationRequest,
        started_at: float,
    ) -> ConversationResult:
        completed = reservation_result.completed
        if completed is None or completed.conversation_id != request.conversation_id:
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE)
        if completed.chat_outcome is not ChatOutcome.ANSWER:
            chat = GroundedChatResult(
                outcome=completed.chat_outcome,
                reason=completed.chat_reason,
                answer=completed.assistant_text,
                retrieval_run_id=completed.retrieval_run_id,
            )
            self._log(
                "conversation_completed",
                status=completed.status.value,
                reason=chat.reason.value,
                ordinal=completed.ordinal,
                reference_count=0,
                outcome=chat.outcome.value,
                duration_ms=self._duration_ms(started_at),
            )
            return ConversationResult(
                conversation_id=completed.conversation_id,
                exchange_id=completed.exchange_id,
                status=ConversationExchangeStatus.COMPLETED,
                duplicate=True,
                chat=chat,
            )

        try:
            chat = await self._replay_answer(completed)
        except Exception:
            chat = self._fixed_refusal(
                ChatReasonCode.CITATION_REVALIDATION_FAILURE, completed.retrieval_run_id
            )
            self._log(
                "conversation_failed",
                status=completed.status.value,
                reason=chat.reason.value,
                ordinal=completed.ordinal,
                reference_count=len(completed.references),
                error_code=chat.reason.value,
                outcome=chat.outcome.value,
                duration_ms=self._duration_ms(started_at),
            )
        else:
            self._log(
                "conversation_completed",
                status=completed.status.value,
                reason=chat.reason.value,
                ordinal=completed.ordinal,
                reference_count=len(completed.references),
                outcome=chat.outcome.value,
                duration_ms=self._duration_ms(started_at),
            )
        return ConversationResult(
            conversation_id=completed.conversation_id,
            exchange_id=completed.exchange_id,
            status=ConversationExchangeStatus.COMPLETED,
            duplicate=True,
            chat=chat,
        )

    async def _replay_answer(self, completed: PersistedConversationExchange) -> GroundedChatResult:
        if completed.retrieval_run_id is None or not completed.citation_ids:
            raise ValueError
        citations: list[ResolvedCitation] = []
        document_ids: list[UUID] = []
        for citation_id in completed.citation_ids:
            value = await self._citation_resolver.resolve(citation_id, completed.retrieval_run_id)
            citation = self._validated(value, ResolvedCitation)
            if (
                citation.citation_id != citation_id
                or citation.retrieval_run_id != completed.retrieval_run_id
            ):
                raise ValueError
            citations.append(citation)
            if citation.document_id not in document_ids:
                document_ids.append(citation.document_id)
        if tuple(document_ids) != completed.document_ids:
            raise ValueError
        return GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer=completed.assistant_text,
            retrieval_run_id=completed.retrieval_run_id,
            citations=tuple(citations),
            provider=completed.provider,
            model=completed.model,
            provider_request_id=completed.provider_request_id,
        )

    @staticmethod
    def _validated(value: object, model_type: type[_Model]) -> _Model:
        if not isinstance(value, model_type):
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE)
        model_class: Any = model_type
        model_value: Any = value
        return model_class.model_validate(model_value.model_dump())

    @staticmethod
    def _fixed_refusal(reason: ChatReasonCode, retrieval_run_id: UUID | None) -> GroundedChatResult:
        decision = refusal_decision(reason)
        return GroundedChatResult(
            outcome=ChatOutcome.REFUSAL,
            reason=reason,
            answer=decision.fixed_text or "",
            retrieval_run_id=retrieval_run_id,
        )

    @staticmethod
    def _duplicate_identity(
        reservation_result: ConversationReservationResult,
        request: ConversationRequest,
    ) -> tuple[UUID, UUID]:
        """Validate persisted duplicate pointers before replaying their status."""

        conversation_id = reservation_result.conversation_id
        exchange_id = reservation_result.exchange_id
        if (
            conversation_id is None
            or conversation_id != request.conversation_id
            or exchange_id is None
        ):
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE)
        return conversation_id, exchange_id

    def _log_repository_error(
        self,
        error: ConversationError,
        *,
        started_at: float | None,
        ordinal: int | None = None,
        state_version: int | None = None,
    ) -> None:
        event = {
            ConversationErrorCode.BUSY: "conversation_busy",
            ConversationErrorCode.IN_PROGRESS: "conversation_busy",
            ConversationErrorCode.CONFLICT: "conversation_conflict",
            ConversationErrorCode.EXPIRED: "conversation_expired",
            ConversationErrorCode.LEASE_EXPIRED: "conversation_expired",
        }.get(error.code, "conversation_failed")
        self._log(
            event,
            reason=error.code.value,
            ordinal=ordinal,
            state_version=state_version,
            error_code=error.code.value,
            duration_ms=self._duration_ms(started_at) if started_at is not None else None,
        )

    def _log(
        self,
        event: str,
        *,
        status: str | None = None,
        reason: str | None = None,
        ordinal: int | None = None,
        state_version: int | None = None,
        recent_turn_count: int | None = None,
        reference_count: int | None = None,
        error_code: str | None = None,
        duration_ms: float | None = None,
        outcome: str | None = None,
    ) -> None:
        extra = {
            "conversation_status": status,
            "conversation_reason": reason,
            "conversation_ordinal": ordinal,
            "conversation_state_version": state_version,
            "conversation_recent_turn_count": recent_turn_count,
            "conversation_reference_count": reference_count,
            "conversation_error_code": error_code,
            "duration_ms": duration_ms,
            "outcome": outcome,
        }
        self._logger.info(event, extra=extra)

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)
