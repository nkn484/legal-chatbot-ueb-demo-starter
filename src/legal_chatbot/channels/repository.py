"""PostgreSQL persistence adapters for lease-backed channel delivery state."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.errors import ChannelError, ChannelErrorCode
from legal_chatbot.channels.models import (
    ChannelBindingReservation,
    ChannelBindingReservationStatus,
    ChannelBindingStatus,
    ChannelDeliveryReceipt,
    ChannelDeliveryReceiptStatus,
    ChannelKind,
    ChannelOutboundMessage,
    ChannelOutboundReservation,
    ChannelOutboundReservationStatus,
    ChannelOutboundStatus,
)
from legal_chatbot.channels.orm import ChannelConversationBinding, ChannelOutboundDelivery
from legal_chatbot.channels.port import ChannelBindingRepositoryPort, ChannelOutboundRepositoryPort

_HMAC_PATTERN = re.compile(r"[0-9a-f]{64}")
_SAFE_ERROR_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def _repository_now(now: datetime) -> datetime:
    """Normalize caller time while rejecting ambiguous local timestamps."""

    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
    return now.astimezone(UTC)


def _is_postgresql_unique_violation(error: IntegrityError) -> bool:
    """Recognize only SQLSTATE 23505 through bounded driver exception wrappers."""

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
        for nested in (getattr(current, "orig", None), current.__cause__, current.__context__):
            if isinstance(nested, BaseException):
                pending.append(nested)
    return False


def _persistence_error(error: Exception) -> ChannelError:
    """Prevent driver, validation, and caller details from crossing this boundary."""

    if isinstance(error, ChannelError):
        return error
    return ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)


def _valid_hmac(value: object) -> bool:
    return isinstance(value, str) and _HMAC_PATTERN.fullmatch(value) is not None


def _valid_safe_error_code(value: object) -> bool:
    return isinstance(value, str) and _SAFE_ERROR_CODE_PATTERN.fullmatch(value) is not None


def _binding_reservation(binding: ChannelConversationBinding) -> ChannelBindingReservation:
    """Map a stored binding without exposing identity or failure metadata."""

    status = ChannelBindingStatus(binding.status)
    if status is ChannelBindingStatus.BINDING:
        if binding.lease_expires_at is None:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
        return ChannelBindingReservation(
            binding_id=binding.id,
            status=ChannelBindingReservationStatus.RESERVED,
            lease_expires_at=binding.lease_expires_at,
        )
    if status is ChannelBindingStatus.ACTIVE:
        if binding.conversation_id is None:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
        return ChannelBindingReservation(
            binding_id=binding.id,
            status=ChannelBindingReservationStatus.ACTIVE,
            conversation_id=binding.conversation_id,
        )
    return ChannelBindingReservation(
        binding_id=binding.id,
        status=ChannelBindingReservationStatus.FAILED,
    )


def _processing_binding_reservation(
    binding: ChannelConversationBinding,
) -> ChannelBindingReservation:
    """Return the exact in-flight lease rather than minting a replacement token."""

    if binding.lease_expires_at is None:
        raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
    return ChannelBindingReservation(
        binding_id=binding.id,
        status=ChannelBindingReservationStatus.PROCESSING,
        lease_expires_at=binding.lease_expires_at,
    )


def _outbound_reservation(delivery: ChannelOutboundDelivery) -> ChannelOutboundReservation:
    """Map durable delivery state to its deliberately metadata-free result contract."""

    try:
        status = ChannelOutboundStatus(delivery.status)
        mapped_status = {
            ChannelOutboundStatus.PENDING: ChannelOutboundReservationStatus.RESERVED,
            ChannelOutboundStatus.SENDING: ChannelOutboundReservationStatus.PROCESSING,
            ChannelOutboundStatus.SENT: ChannelOutboundReservationStatus.SENT,
            ChannelOutboundStatus.FAILED: ChannelOutboundReservationStatus.FAILED,
            ChannelOutboundStatus.UNKNOWN: ChannelOutboundReservationStatus.UNKNOWN,
            ChannelOutboundStatus.ABANDONED: ChannelOutboundReservationStatus.ABANDONED,
        }[status]
        return ChannelOutboundReservation(
            outbound_id=delivery.id,
            binding_id=delivery.binding_id,
            exchange_id=delivery.exchange_id,
            status=mapped_status,
            attempt_count=delivery.attempt_count,
            safe_error_code=delivery.safe_error_code,
        )
    except (KeyError, ValidationError, ValueError, TypeError):
        raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None


class PostgresChannelBindingRepository(ChannelBindingRepositoryPort):
    """Persist identity bindings in short lock-scoped transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ChannelSettings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def reserve(self, identity_hmac: str, now: datetime) -> ChannelBindingReservation:
        now = _repository_now(now)
        if not _valid_hmac(identity_hmac):
            raise ChannelError(ChannelErrorCode.BINDING_FAILED)
        lease_expires_at = now + timedelta(seconds=self._settings.binding_lease_seconds)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    binding = await session.scalar(
                        select(ChannelConversationBinding)
                        .where(
                            ChannelConversationBinding.channel_kind
                            == ChannelKind.ZALO_OFFICIAL_BOT.value,
                            ChannelConversationBinding.identity_hmac == identity_hmac,
                        )
                        .with_for_update()
                    )
                    if binding is None:
                        binding = ChannelConversationBinding(
                            id=uuid4(),
                            channel_kind=ChannelKind.ZALO_OFFICIAL_BOT.value,
                            identity_hmac=identity_hmac,
                            status=ChannelBindingStatus.BINDING.value,
                            lease_expires_at=lease_expires_at,
                        )
                        session.add(binding)
                        await session.flush()
                        return _binding_reservation(binding)
                    return self._reserve_existing(binding, now, lease_expires_at)
        except IntegrityError as error:
            if _is_postgresql_unique_violation(error):
                return await self._reserve_after_unique_race(identity_hmac, now, lease_expires_at)
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _persistence_error(error) from None

    async def activate(
        self, reservation: ChannelBindingReservation, conversation_id: UUID, now: datetime
    ) -> ChannelBindingReservation:
        now = _repository_now(now)
        if (
            not isinstance(reservation, ChannelBindingReservation)
            or reservation.status is not ChannelBindingReservationStatus.RESERVED
            or reservation.lease_expires_at is None
            or not isinstance(conversation_id, UUID)
        ):
            raise ChannelError(ChannelErrorCode.BINDING_FAILED)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    binding = await session.scalar(
                        select(ChannelConversationBinding)
                        .where(ChannelConversationBinding.id == reservation.binding_id)
                        .with_for_update()
                    )
                    lease = binding.lease_expires_at if binding is not None else None
                    if (
                        binding is None
                        or binding.status != ChannelBindingStatus.BINDING.value
                        or lease != reservation.lease_expires_at
                        or lease is None
                        or lease <= now
                    ):
                        raise ChannelError(ChannelErrorCode.BINDING_FAILED)
                    binding.status = ChannelBindingStatus.ACTIVE.value
                    binding.conversation_id = conversation_id
                    binding.lease_expires_at = None
                    binding.safe_error_code = None
                    binding.activated_at = now
                    binding.updated_at = now
                    await session.flush()
                    return _binding_reservation(binding)
        except IntegrityError:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _persistence_error(error) from None

    async def fail(
        self, reservation: ChannelBindingReservation, safe_error_code: str, now: datetime
    ) -> ChannelBindingReservation:
        now = _repository_now(now)
        if (
            not isinstance(reservation, ChannelBindingReservation)
            or reservation.status is not ChannelBindingReservationStatus.RESERVED
            or reservation.lease_expires_at is None
            or not _valid_safe_error_code(safe_error_code)
        ):
            raise ChannelError(ChannelErrorCode.BINDING_FAILED)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    binding = await session.scalar(
                        select(ChannelConversationBinding)
                        .where(ChannelConversationBinding.id == reservation.binding_id)
                        .with_for_update()
                    )
                    lease = binding.lease_expires_at if binding is not None else None
                    if (
                        binding is None
                        or binding.status != ChannelBindingStatus.BINDING.value
                        or lease != reservation.lease_expires_at
                        or lease is None
                        or lease <= now
                    ):
                        raise ChannelError(ChannelErrorCode.BINDING_FAILED)
                    binding.status = ChannelBindingStatus.FAILED.value
                    binding.conversation_id = None
                    binding.lease_expires_at = None
                    binding.safe_error_code = safe_error_code
                    binding.activated_at = None
                    binding.updated_at = now
                    await session.flush()
                    return _binding_reservation(binding)
        except IntegrityError:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _persistence_error(error) from None

    @staticmethod
    def _reserve_existing(
        binding: ChannelConversationBinding, now: datetime, lease_expires_at: datetime
    ) -> ChannelBindingReservation:
        if binding.status == ChannelBindingStatus.ACTIVE.value:
            return _binding_reservation(binding)
        if (
            binding.status == ChannelBindingStatus.BINDING.value
            and binding.lease_expires_at is not None
            and binding.lease_expires_at > now
        ):
            return _processing_binding_reservation(binding)
        if binding.status not in {
            ChannelBindingStatus.BINDING.value,
            ChannelBindingStatus.FAILED.value,
        }:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
        binding.status = ChannelBindingStatus.BINDING.value
        binding.conversation_id = None
        binding.lease_expires_at = lease_expires_at
        binding.safe_error_code = None
        binding.activated_at = None
        binding.updated_at = now
        return _binding_reservation(binding)

    async def _reserve_after_unique_race(
        self, identity_hmac: str, now: datetime, lease_expires_at: datetime
    ) -> ChannelBindingReservation:
        """Perform the single permitted post-23505 read and state mapping."""

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    binding = await session.scalar(
                        select(ChannelConversationBinding)
                        .where(
                            ChannelConversationBinding.channel_kind
                            == ChannelKind.ZALO_OFFICIAL_BOT.value,
                            ChannelConversationBinding.identity_hmac == identity_hmac,
                        )
                        .with_for_update()
                    )
                    if binding is None:
                        raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
                    return self._reserve_existing(binding, now, lease_expires_at)
        except Exception as error:
            raise _persistence_error(error) from None


class PostgresChannelOutboundRepository(ChannelOutboundRepositoryPort):
    """Persist the single permitted outbound attempt for a bot delivery."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], settings: ChannelSettings
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def reserve(
        self, binding_id: UUID, message: ChannelOutboundMessage, now: datetime
    ) -> ChannelOutboundReservation:
        now = _repository_now(now)
        if not isinstance(binding_id, UUID) or not isinstance(message, ChannelOutboundMessage):
            raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await self._require_active_binding(session, binding_id, message.identity_hmac)
                    delivery = await session.scalar(
                        select(ChannelOutboundDelivery)
                        .where(
                            ChannelOutboundDelivery.channel_kind
                            == ChannelKind.ZALO_OFFICIAL_BOT.value,
                            ChannelOutboundDelivery.delivery_hmac == message.delivery_hmac,
                        )
                        .with_for_update()
                    )
                    if delivery is not None:
                        return self._existing_delivery_reservation(
                            delivery, binding_id, message.exchange_id
                        )
                    delivery = ChannelOutboundDelivery(
                        id=uuid4(),
                        channel_kind=ChannelKind.ZALO_OFFICIAL_BOT.value,
                        binding_id=binding_id,
                        exchange_id=message.exchange_id,
                        delivery_hmac=message.delivery_hmac,
                        status=ChannelOutboundStatus.PENDING.value,
                        attempt_count=0,
                    )
                    session.add(delivery)
                    await session.flush()
                    return _outbound_reservation(delivery)
        except IntegrityError as error:
            if _is_postgresql_unique_violation(error):
                return await self._reserve_after_unique_race(binding_id, message)
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _persistence_error(error) from None

    async def mark_sending(
        self, reservation: ChannelOutboundReservation, now: datetime
    ) -> ChannelOutboundReservation:
        _repository_now(now)
        if (
            not isinstance(reservation, ChannelOutboundReservation)
            or reservation.status is not ChannelOutboundReservationStatus.RESERVED
        ):
            raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    delivery = await self._locked_delivery(session, reservation)
                    if delivery.status == ChannelOutboundStatus.PENDING.value:
                        result = await session.execute(
                            update(ChannelOutboundDelivery)
                            .where(
                                ChannelOutboundDelivery.id == reservation.outbound_id,
                                ChannelOutboundDelivery.binding_id == reservation.binding_id,
                                ChannelOutboundDelivery.exchange_id == reservation.exchange_id,
                                ChannelOutboundDelivery.status
                                == ChannelOutboundStatus.PENDING.value,
                                ChannelOutboundDelivery.attempt_count == 0,
                            )
                            .values(
                                status=ChannelOutboundStatus.SENDING.value,
                                attempt_count=1,
                                sending_at=now,
                            )
                        )
                        if getattr(result, "rowcount", 0) == 1:
                            return ChannelOutboundReservation(
                                outbound_id=reservation.outbound_id,
                                binding_id=reservation.binding_id,
                                exchange_id=reservation.exchange_id,
                                status=ChannelOutboundReservationStatus.SENDING,
                                attempt_count=1,
                            )
                        delivery = await self._locked_delivery(session, reservation)
                    return _outbound_reservation(delivery)
        except IntegrityError:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _persistence_error(error) from None

    async def complete(
        self,
        reservation: ChannelOutboundReservation,
        receipt: ChannelDeliveryReceipt,
        now: datetime,
    ) -> ChannelOutboundReservation:
        now = _repository_now(now)
        if (
            not isinstance(reservation, ChannelOutboundReservation)
            or reservation.status is not ChannelOutboundReservationStatus.SENDING
            or not isinstance(receipt, ChannelDeliveryReceipt)
        ):
            raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    delivery = await self._locked_delivery(session, reservation)
                    if delivery.status in {
                        ChannelOutboundStatus.SENT.value,
                        ChannelOutboundStatus.FAILED.value,
                        ChannelOutboundStatus.UNKNOWN.value,
                        ChannelOutboundStatus.ABANDONED.value,
                    }:
                        return _outbound_reservation(delivery)
                    if (
                        delivery.status != ChannelOutboundStatus.SENDING.value
                        or delivery.attempt_count != 1
                    ):
                        raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
                    status, safe_error_code = self._completion_state(receipt)
                    delivery.status = status.value
                    delivery.safe_error_code = safe_error_code
                    delivery.completed_at = now
                    await session.flush()
                    return _outbound_reservation(delivery)
        except IntegrityError:
            raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE) from None
        except Exception as error:
            raise _persistence_error(error) from None

    async def _require_active_binding(
        self, session: AsyncSession, binding_id: UUID, identity_hmac: str
    ) -> ChannelConversationBinding:
        binding = await session.scalar(
            select(ChannelConversationBinding)
            .where(ChannelConversationBinding.id == binding_id)
            .with_for_update()
        )
        if (
            binding is None
            or binding.status != ChannelBindingStatus.ACTIVE.value
            or binding.identity_hmac != identity_hmac
        ):
            raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
        return binding

    @staticmethod
    def _existing_delivery_reservation(
        delivery: ChannelOutboundDelivery, binding_id: UUID, exchange_id: UUID
    ) -> ChannelOutboundReservation:
        if delivery.binding_id != binding_id or delivery.exchange_id != exchange_id:
            raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
        return _outbound_reservation(delivery)

    async def _reserve_after_unique_race(
        self, binding_id: UUID, message: ChannelOutboundMessage
    ) -> ChannelOutboundReservation:
        """Read the one conflicting delivery once after a SQLSTATE 23505 insert race."""

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await self._require_active_binding(session, binding_id, message.identity_hmac)
                    delivery = await session.scalar(
                        select(ChannelOutboundDelivery)
                        .where(
                            ChannelOutboundDelivery.channel_kind
                            == ChannelKind.ZALO_OFFICIAL_BOT.value,
                            ChannelOutboundDelivery.delivery_hmac == message.delivery_hmac,
                        )
                        .with_for_update()
                    )
                    if delivery is None:
                        raise ChannelError(ChannelErrorCode.PERSISTENCE_FAILURE)
                    return self._existing_delivery_reservation(
                        delivery, binding_id, message.exchange_id
                    )
        except Exception as error:
            raise _persistence_error(error) from None

    @staticmethod
    async def _locked_delivery(
        session: AsyncSession, reservation: ChannelOutboundReservation
    ) -> ChannelOutboundDelivery:
        delivery = await session.scalar(
            select(ChannelOutboundDelivery)
            .where(ChannelOutboundDelivery.id == reservation.outbound_id)
            .with_for_update()
        )
        if (
            delivery is None
            or delivery.binding_id != reservation.binding_id
            or delivery.exchange_id != reservation.exchange_id
        ):
            raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
        return delivery

    @staticmethod
    def _completion_state(
        receipt: ChannelDeliveryReceipt,
    ) -> tuple[ChannelOutboundStatus, str | None]:
        if receipt.status is ChannelDeliveryReceiptStatus.SENT:
            return ChannelOutboundStatus.SENT, None
        if receipt.status is ChannelDeliveryReceiptStatus.REJECTED:
            return ChannelOutboundStatus.FAILED, receipt.safe_error_code
        if receipt.status in {
            ChannelDeliveryReceiptStatus.TIMEOUT,
            ChannelDeliveryReceiptStatus.UNAVAILABLE,
            ChannelDeliveryReceiptStatus.INVALID_RESPONSE,
        }:
            return ChannelOutboundStatus.UNKNOWN, receipt.safe_error_code
        raise ChannelError(ChannelErrorCode.OUTBOUND_STATE_INVALID)
