"""PostgreSQL persistence adapter for bounded conversation state."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import ceil
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import (
    ConversationCompactionCandidate,
    ConversationCompactionPlan,
    ConversationExchangeStatus,
    ConversationReference,
    ConversationReferenceKind,
    ConversationRequest,
    ConversationReservation,
    ConversationReservationResult,
    ConversationReservationStatus,
    ConversationStateSnapshot,
    ConversationStateUpdate,
    ConversationTurn,
    ConversationTurnRole,
    CreateConversationResult,
    PersistedConversationExchange,
)
from legal_chatbot.conversation.orm import (
    Conversation,
    ConversationExchange,
    ConversationExchangeReference,
)
from legal_chatbot.conversation.policy import delivery_key_sha256
from legal_chatbot.conversation.port import ConversationRepositoryPort

_PURGE_LIMIT_MAX = 1_000
_FAILURE_LEASE_EXPIRED = "LEASE_EXPIRED"
_TERMINAL_STATUS_VALUES = (
    ConversationExchangeStatus.COMPLETED.value,
    ConversationExchangeStatus.FAILED.value,
    ConversationExchangeStatus.ABANDONED.value,
)


def _repository_now(now: datetime) -> datetime:
    """Normalize an aware repository-clock value without retaining caller input."""

    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    return now.astimezone(UTC)


def _conversation_error_for_unexpected(error: Exception) -> ConversationError:
    """Keep persistence failures code-only regardless of driver or validation detail."""

    if isinstance(error, ConversationError):
        return error
    if isinstance(error, (ValidationError, TypeError, ValueError)):
        return ConversationError(ConversationErrorCode.STATE_INVALID)
    return ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE)


def _is_postgresql_unique_violation(error: IntegrityError) -> bool:
    """Recognize only SQLSTATE 23505 through bounded SQLAlchemy driver wrappers."""

    pending: list[BaseException] = [error]
    inspected: set[int] = set()
    while pending and len(inspected) < 6:
        current = pending.pop(0)
        if id(current) in inspected:
            continue
        inspected.add(id(current))
        if (
            getattr(current, "sqlstate", None) == "23505"
            or getattr(current, "pgcode", None) == "23505"
        ):
            return True
        for nested in (
            getattr(current, "orig", None),
            current.__cause__,
            current.__context__,
        ):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _derived_references(chat: GroundedChatResult) -> tuple[ConversationReference, ...]:
    """Derive server-owned reference pointers from validated answer citations only."""

    if not isinstance(chat, GroundedChatResult):
        raise ConversationError(ConversationErrorCode.STATE_INVALID)
    if chat.outcome is not ChatOutcome.ANSWER:
        return ()

    citation_references = tuple(
        ConversationReference(
            kind=ConversationReferenceKind.CITATION,
            reference_id=citation.citation_id,
            ordinal=ordinal,
        )
        for ordinal, citation in enumerate(chat.citations)
    )
    document_ids: set[UUID] = set()
    document_references: list[ConversationReference] = []
    for citation in chat.citations:
        if citation.document_id not in document_ids:
            document_ids.add(citation.document_id)
            document_references.append(
                ConversationReference(
                    kind=ConversationReferenceKind.DOCUMENT,
                    reference_id=citation.document_id,
                    ordinal=len(document_references),
                )
            )
    return citation_references + tuple(document_references)


def _compaction_candidate(
    exchange: ConversationExchange, citation_count: int, document_count: int
) -> ConversationCompactionCandidate:
    """Map a terminal ORM row to the bounded compaction contract."""

    return ConversationCompactionCandidate(
        exchange_id=exchange.id,
        ordinal=exchange.ordinal,
        status=ConversationExchangeStatus(exchange.status),
        user_text=exchange.user_text,
        assistant_text=exchange.assistant_text,
        chat_outcome=ChatOutcome(exchange.chat_outcome) if exchange.chat_outcome else None,
        chat_reason=exchange.chat_reason,
        citation_count=citation_count,
        document_count=document_count,
    )


class PostgresConversationRepository(ConversationRepositoryPort):
    """Persist short-lived conversation state using explicit bounded transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ConversationSettings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def create_conversation(self, now: datetime) -> CreateConversationResult:
        now = _repository_now(now)
        conversation = Conversation(
            id=uuid4(),
            state_version=0,
            expires_at=now + timedelta(seconds=self._settings.retention_seconds),
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    session.add(conversation)
                    await session.flush()
            return CreateConversationResult(conversation_id=conversation.id)
        except Exception as error:
            raise _conversation_error_for_unexpected(error) from None

    async def reserve(
        self, request: ConversationRequest, now: datetime
    ) -> ConversationReservationResult:
        now = _repository_now(now)
        if not isinstance(request, ConversationRequest):
            raise ConversationError(ConversationErrorCode.DELIVERY_INVALID)
        digest = ""
        try:
            digest = delivery_key_sha256(request.delivery_id)
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
                    conversation = await self._locked_active_conversation(
                        session, request.conversation_id, now
                    )
                    await self._abandon_stale_processing(session, conversation.id, now)
                    existing = await session.scalar(
                        select(ConversationExchange).where(
                            ConversationExchange.conversation_id == conversation.id,
                            ConversationExchange.delivery_key_sha256 == digest,
                        )
                    )
                    if existing is not None:
                        return await self._reservation_for_existing(session, existing)

                    live_processing = await session.scalar(
                        select(ConversationExchange.id)
                        .where(
                            ConversationExchange.conversation_id == conversation.id,
                            ConversationExchange.status
                            == ConversationExchangeStatus.PROCESSING.value,
                        )
                        .limit(1)
                    )
                    if live_processing is not None:
                        raise ConversationError(ConversationErrorCode.BUSY)

                    maximum_ordinal = await session.scalar(
                        select(func.max(ConversationExchange.ordinal)).where(
                            ConversationExchange.conversation_id == conversation.id
                        )
                    )
                    exchange = ConversationExchange(
                        id=uuid4(),
                        conversation_id=conversation.id,
                        delivery_key_sha256=digest,
                        ordinal=int(maximum_ordinal or 0) + 1,
                        status=ConversationExchangeStatus.PROCESSING.value,
                        lease_expires_at=now
                        + timedelta(seconds=self._settings.processing_lease_seconds),
                        user_text=request.text,
                    )
                    session.add(exchange)
                    await session.flush()
                    compaction_plan = await self._compaction_plan_for_reservation(
                        session, conversation.id
                    )
                    snapshot = await self._load_snapshot_for_conversation(
                        session, conversation, now
                    )
                    return ConversationReservationResult(
                        status=ConversationReservationStatus.RESERVED,
                        reservation=ConversationReservation(
                            conversation_id=conversation.id,
                            exchange_id=exchange.id,
                            ordinal=exchange.ordinal,
                            expected_state_version=conversation.state_version,
                            snapshot=snapshot,
                            compaction_plan=compaction_plan,
                        ),
                    )
        except IntegrityError as error:
            if _is_postgresql_unique_violation(error):
                return await self._reservation_after_integrity_race(request, digest)
            raise ConversationError(ConversationErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _conversation_error_for_unexpected(error) from None

    async def load_snapshot(
        self, conversation_id: UUID, now: datetime
    ) -> ConversationStateSnapshot:
        now = _repository_now(now)
        if not isinstance(conversation_id, UUID):
            raise ConversationError(ConversationErrorCode.STATE_INVALID)
        try:
            async with self._session_factory() as session:
                conversation = await self._active_conversation(session, conversation_id, now)
                return await self._load_snapshot_for_conversation(session, conversation, now)
        except Exception as error:
            raise _conversation_error_for_unexpected(error) from None

    async def complete(
        self,
        reservation: ConversationReservation,
        chat: GroundedChatResult,
        state_update: ConversationStateUpdate,
        now: datetime,
    ) -> PersistedConversationExchange:
        now = _repository_now(now)
        if (
            not isinstance(reservation, ConversationReservation)
            or not isinstance(chat, GroundedChatResult)
            or not isinstance(state_update, ConversationStateUpdate)
            or state_update.expected_state_version != reservation.expected_state_version
        ):
            raise ConversationError(ConversationErrorCode.STATE_INVALID)
        if state_update.compacted_exchange_ids != reservation.compaction_plan.exchange_ids:
            raise ConversationError(ConversationErrorCode.CONFLICT)
        try:
            references = _derived_references(chat)
            async with self._session_factory() as session:
                async with session.begin():
                    conversation = await self._locked_active_conversation(
                        session, reservation.conversation_id, now
                    )
                    if conversation.state_version != reservation.expected_state_version:
                        raise ConversationError(ConversationErrorCode.CONFLICT)
                    exchange = await session.scalar(
                        select(ConversationExchange)
                        .where(
                            ConversationExchange.id == reservation.exchange_id,
                            ConversationExchange.conversation_id == reservation.conversation_id,
                            ConversationExchange.ordinal == reservation.ordinal,
                        )
                        .with_for_update()
                    )
                    if (
                        exchange is None
                        or exchange.status != ConversationExchangeStatus.PROCESSING.value
                    ):
                        raise ConversationError(ConversationErrorCode.CONFLICT)
                    if exchange.lease_expires_at is None or exchange.lease_expires_at <= now:
                        raise ConversationError(ConversationErrorCode.EXPIRED)
                    candidates = await self._locked_compaction_candidates(
                        session,
                        reservation.conversation_id,
                        reservation.compaction_plan,
                    )

                    exchange.status = ConversationExchangeStatus.COMPLETED.value
                    exchange.lease_expires_at = None
                    exchange.assistant_text = chat.answer
                    exchange.chat_outcome = chat.outcome.value
                    exchange.chat_reason = chat.reason.value
                    exchange.retrieval_run_id = chat.retrieval_run_id
                    exchange.provider = chat.provider
                    exchange.model = chat.model
                    exchange.request_id = chat.provider_request_id
                    exchange.completed_at = now
                    session.add_all(
                        ConversationExchangeReference(
                            exchange_id=exchange.id,
                            kind=reference.kind.value,
                            reference_id=reference.reference_id,
                            ordinal=reference.ordinal,
                        )
                        for reference in references
                    )
                    cas_result = await session.execute(
                        update(Conversation)
                        .where(
                            Conversation.id == conversation.id,
                            Conversation.state_version == reservation.expected_state_version,
                        )
                        .values(
                            state_version=Conversation.state_version + 1,
                            rolling_summary=state_update.rolling_summary,
                            active_topic=state_update.active_topic,
                            updated_at=now,
                            expires_at=now + timedelta(seconds=self._settings.retention_seconds),
                        )
                    )
                    if cas_result.rowcount != 1:
                        raise ConversationError(ConversationErrorCode.CONFLICT)
                    if candidates:
                        deleted = await session.execute(
                            delete(ConversationExchange).where(
                                ConversationExchange.conversation_id == conversation.id,
                                ConversationExchange.id.in_(
                                    tuple(candidate.id for candidate in candidates)
                                ),
                            )
                        )
                        if deleted.rowcount != len(candidates):
                            raise ConversationError(ConversationErrorCode.CONFLICT)
                    await session.flush()
                    terminal_count = await session.scalar(
                        select(func.count())
                        .select_from(ConversationExchange)
                        .where(
                            ConversationExchange.conversation_id == conversation.id,
                            ConversationExchange.status.in_(
                                (
                                    ConversationExchangeStatus.COMPLETED.value,
                                    ConversationExchangeStatus.FAILED.value,
                                    ConversationExchangeStatus.ABANDONED.value,
                                )
                            ),
                        )
                    )
                    if int(terminal_count or 0) > self._settings.retained_exchange_limit:
                        raise ConversationError(ConversationErrorCode.CONFLICT)
                    return self._persisted_exchange(exchange, references)
        except Exception as error:
            raise _conversation_error_for_unexpected(error) from None

    async def purge_expired(self, now: datetime, limit: int) -> int:
        now = _repository_now(now)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= _PURGE_LIMIT_MAX
        ):
            raise ConversationError(ConversationErrorCode.STATE_INVALID)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    conversation_ids = list(
                        (
                            await session.scalars(
                                select(Conversation.id)
                                .where(
                                    (Conversation.expires_at <= now)
                                    | (Conversation.deleted_at.is_not(None))
                                )
                                .order_by(Conversation.expires_at.asc(), Conversation.id.asc())
                                .limit(limit)
                                .with_for_update(skip_locked=True)
                            )
                        ).all()
                    )
                    if not conversation_ids:
                        return 0
                    result = await session.execute(
                        delete(Conversation).where(Conversation.id.in_(conversation_ids))
                    )
                    return int(result.rowcount or 0)
        except Exception as error:
            raise _conversation_error_for_unexpected(error) from None

    async def _locked_active_conversation(
        self, session: AsyncSession, conversation_id: UUID, now: datetime
    ) -> Conversation:
        conversation = await session.scalar(
            select(Conversation).where(Conversation.id == conversation_id).with_for_update()
        )
        return self._require_active_conversation(conversation, now)

    async def _active_conversation(
        self, session: AsyncSession, conversation_id: UUID, now: datetime
    ) -> Conversation:
        conversation = await session.scalar(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return self._require_active_conversation(conversation, now)

    @staticmethod
    def _require_active_conversation(
        conversation: Conversation | None, now: datetime
    ) -> Conversation:
        if conversation is None or conversation.deleted_at is not None:
            raise ConversationError(ConversationErrorCode.NOT_FOUND)
        if conversation.expires_at <= now:
            raise ConversationError(ConversationErrorCode.EXPIRED)
        return conversation

    async def _abandon_stale_processing(
        self, session: AsyncSession, conversation_id: UUID, now: datetime
    ) -> None:
        await session.execute(
            update(ConversationExchange)
            .where(
                ConversationExchange.conversation_id == conversation_id,
                ConversationExchange.status == ConversationExchangeStatus.PROCESSING.value,
                ConversationExchange.lease_expires_at <= now,
            )
            .values(
                status=ConversationExchangeStatus.ABANDONED.value,
                lease_expires_at=None,
                chat_reason=_FAILURE_LEASE_EXPIRED,
            )
        )

    async def _compaction_plan_for_reservation(
        self, session: AsyncSession, conversation_id: UUID
    ) -> ConversationCompactionPlan:
        terminal_count = await session.scalar(
            select(func.count())
            .select_from(ConversationExchange)
            .where(
                ConversationExchange.conversation_id == conversation_id,
                ConversationExchange.status.in_(_TERMINAL_STATUS_VALUES),
            )
        )
        candidate_count = max(
            0, int(terminal_count or 0) + 1 - self._settings.retained_exchange_limit
        )
        if candidate_count == 0:
            return ConversationCompactionPlan()
        rows = (
            await session.execute(
                select(
                    ConversationExchange,
                    func.count(ConversationExchangeReference.reference_id)
                    .filter(
                        ConversationExchangeReference.kind
                        == ConversationReferenceKind.CITATION.value
                    )
                    .label("citation_count"),
                    func.count(ConversationExchangeReference.reference_id)
                    .filter(
                        ConversationExchangeReference.kind
                        == ConversationReferenceKind.DOCUMENT.value
                    )
                    .label("document_count"),
                )
                .outerjoin(
                    ConversationExchangeReference,
                    ConversationExchangeReference.exchange_id == ConversationExchange.id,
                )
                .where(
                    ConversationExchange.conversation_id == conversation_id,
                    ConversationExchange.status.in_(_TERMINAL_STATUS_VALUES),
                )
                .group_by(ConversationExchange.id)
                .order_by(ConversationExchange.ordinal.asc())
                .limit(candidate_count)
            )
        ).all()
        candidates = tuple(
            _compaction_candidate(exchange, int(citation_count), int(document_count))
            for exchange, citation_count, document_count in rows
        )
        return ConversationCompactionPlan(
            exchange_ids=tuple(candidate.exchange_id for candidate in candidates),
            candidates=candidates,
        )

    async def _locked_compaction_candidates(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        plan: ConversationCompactionPlan,
    ) -> tuple[ConversationExchange, ...]:
        if not plan.exchange_ids:
            return ()
        candidates = tuple(
            (
                await session.scalars(
                    select(ConversationExchange)
                    .where(
                        ConversationExchange.conversation_id == conversation_id,
                        ConversationExchange.id.in_(plan.exchange_ids),
                    )
                    .order_by(ConversationExchange.ordinal.asc())
                    .with_for_update()
                )
            ).all()
        )
        if tuple(candidate.id for candidate in candidates) != plan.exchange_ids or any(
            candidate.status not in _TERMINAL_STATUS_VALUES for candidate in candidates
        ):
            raise ConversationError(ConversationErrorCode.CONFLICT)
        return candidates

    async def _reservation_for_existing(
        self, session: AsyncSession, exchange: ConversationExchange
    ) -> ConversationReservationResult:
        if exchange.status == ConversationExchangeStatus.COMPLETED.value:
            return ConversationReservationResult(
                status=ConversationReservationStatus.DUPLICATE_COMPLETED,
                completed=await self._persisted_exchange_from_database(session, exchange),
            )
        if exchange.status == ConversationExchangeStatus.PROCESSING.value:
            return ConversationReservationResult(
                status=ConversationReservationStatus.DUPLICATE_PROCESSING,
                conversation_id=exchange.conversation_id,
                exchange_id=exchange.id,
            )
        return ConversationReservationResult(
            status=ConversationReservationStatus.DUPLICATE_TERMINAL,
            conversation_id=exchange.conversation_id,
            exchange_id=exchange.id,
        )

    async def _reservation_after_integrity_race(
        self, request: ConversationRequest, digest: str
    ) -> ConversationReservationResult:
        try:
            async with self._session_factory() as session:
                exchange = await session.scalar(
                    select(ConversationExchange).where(
                        ConversationExchange.conversation_id == request.conversation_id,
                        ConversationExchange.delivery_key_sha256 == digest,
                    )
                )
                if exchange is not None:
                    return await self._reservation_for_existing(session, exchange)
        except ConversationError:
            raise
        except Exception:
            pass
        raise ConversationError(ConversationErrorCode.BUSY)

    async def _load_snapshot_for_conversation(
        self, session: AsyncSession, conversation: Conversation, now: datetime
    ) -> ConversationStateSnapshot:
        self._require_active_conversation(conversation, now)
        exchange_limit = ceil(self._settings.recent_completed_turn_limit / 2)
        recent_exchanges = list(
            (
                await session.scalars(
                    select(ConversationExchange)
                    .where(
                        ConversationExchange.conversation_id == conversation.id,
                        ConversationExchange.status == ConversationExchangeStatus.COMPLETED.value,
                    )
                    .order_by(ConversationExchange.ordinal.desc())
                    .limit(exchange_limit)
                )
            ).all()
        )
        chronological_exchanges = tuple(reversed(recent_exchanges))
        turns = tuple(
            turn
            for exchange in chronological_exchanges
            for turn in (
                ConversationTurn(
                    ordinal=(exchange.ordinal * 2) - 1,
                    role=ConversationTurnRole.USER,
                    text=exchange.user_text,
                ),
                ConversationTurn(
                    ordinal=exchange.ordinal * 2,
                    role=ConversationTurnRole.ASSISTANT,
                    text=exchange.assistant_text or "",
                    outcome=ChatOutcome(exchange.chat_outcome) if exchange.chat_outcome else None,
                    reason=ChatReasonCode(exchange.chat_reason) if exchange.chat_reason else None,
                ),
            )
        )[-self._settings.recent_completed_turn_limit :]

        reference_exchanges = (
            select(ConversationExchange.id)
            .where(
                ConversationExchange.conversation_id == conversation.id,
                ConversationExchange.status == ConversationExchangeStatus.COMPLETED.value,
            )
            .order_by(ConversationExchange.ordinal.desc())
            .limit(self._settings.retained_exchange_limit)
        )
        reference_rows = (
            await session.execute(
                select(
                    ConversationExchangeReference.kind,
                    ConversationExchangeReference.reference_id,
                    ConversationExchangeReference.ordinal,
                )
                .where(ConversationExchangeReference.exchange_id.in_(reference_exchanges))
                .join(
                    ConversationExchange,
                    ConversationExchange.id == ConversationExchangeReference.exchange_id,
                )
                .order_by(
                    ConversationExchange.ordinal.desc(),
                    ConversationExchangeReference.ordinal.asc(),
                    ConversationExchangeReference.kind.asc(),
                )
            )
        ).all()
        seen_by_kind: dict[ConversationReferenceKind, set[UUID]] = {
            ConversationReferenceKind.CITATION: set(),
            ConversationReferenceKind.DOCUMENT: set(),
        }
        reference_ordinals = {
            ConversationReferenceKind.CITATION: 0,
            ConversationReferenceKind.DOCUMENT: 0,
        }
        references: list[ConversationReference] = []
        for kind_value, reference_id, _ in reference_rows:
            kind = ConversationReferenceKind(kind_value)
            if (
                reference_id in seen_by_kind[kind]
                or reference_ordinals[kind] >= self._settings.reference_limit
            ):
                continue
            seen_by_kind[kind].add(reference_id)
            references.append(
                ConversationReference(
                    kind=kind,
                    reference_id=reference_id,
                    ordinal=reference_ordinals[kind],
                )
            )
            reference_ordinals[kind] += 1
        return ConversationStateSnapshot(
            state_version=conversation.state_version,
            rolling_summary=conversation.rolling_summary,
            active_topic=conversation.active_topic,
            recent_turns=turns,
            references=tuple(references),
        )

    async def _persisted_exchange_from_database(
        self, session: AsyncSession, exchange: ConversationExchange
    ) -> PersistedConversationExchange:
        reference_rows = (
            await session.execute(
                select(
                    ConversationExchangeReference.kind,
                    ConversationExchangeReference.reference_id,
                    ConversationExchangeReference.ordinal,
                )
                .where(ConversationExchangeReference.exchange_id == exchange.id)
                .order_by(
                    ConversationExchangeReference.kind.asc(),
                    ConversationExchangeReference.ordinal.asc(),
                )
            )
        ).all()
        references = tuple(
            ConversationReference(
                kind=ConversationReferenceKind(kind), reference_id=reference_id, ordinal=ordinal
            )
            for kind, reference_id, ordinal in reference_rows
        )
        return self._persisted_exchange(exchange, references)

    @staticmethod
    def _persisted_exchange(
        exchange: ConversationExchange,
        references: tuple[ConversationReference, ...],
    ) -> PersistedConversationExchange:
        return PersistedConversationExchange(
            conversation_id=exchange.conversation_id,
            exchange_id=exchange.id,
            ordinal=exchange.ordinal,
            status=ConversationExchangeStatus(exchange.status),
            assistant_text=exchange.assistant_text or "",
            chat_outcome=ChatOutcome(exchange.chat_outcome or ""),
            chat_reason=ChatReasonCode(exchange.chat_reason or ""),
            retrieval_run_id=exchange.retrieval_run_id,
            provider=exchange.provider,
            model=exchange.model,
            provider_request_id=exchange.request_id,
            references=references,
        )
