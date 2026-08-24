"""Fail-closed orchestration for authenticated Official Zalo Bot messages."""

from datetime import datetime
from time import perf_counter
from typing import Any, NoReturn, TypeVar, cast
from uuid import UUID

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.errors import ChannelError, ChannelErrorCode
from legal_chatbot.channels.formatter import ChannelFormatter
from legal_chatbot.channels.models import (
    ChannelBindingReservation,
    ChannelBindingReservationStatus,
    ChannelDeliveryReceipt,
    ChannelDeliveryReceiptStatus,
    ChannelFormattedReply,
    ChannelInboundMessage,
    ChannelIngressReceipt,
    ChannelIngressStatus,
    ChannelOutboundMessage,
    ChannelOutboundReservation,
    ChannelOutboundReservationStatus,
)
from legal_chatbot.channels.port import (
    ChannelBindingRepositoryPort,
    ChannelConversationPort,
    ChannelOutboundRepositoryPort,
    ChannelPort,
)
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import (
    ConversationExchangeStatus,
    ConversationRequest,
    ConversationResult,
    CreateConversationResult,
)
from legal_chatbot.core.logging import get_logger

_Model = TypeVar("_Model")


class ChannelService:
    """Coordinate one inbound delivery without owning transactions, locks, or retries."""

    def __init__(
        self,
        binding_repository: ChannelBindingRepositoryPort,
        outbound_repository: ChannelOutboundRepositoryPort,
        conversation: ChannelConversationPort,
        channel: ChannelPort,
        formatter: ChannelFormatter,
        settings: ChannelSettings,
    ) -> None:
        self._binding_repository = binding_repository
        self._outbound_repository = outbound_repository
        self._conversation = conversation
        self._channel = channel
        self._formatter = formatter
        self._settings = settings
        self._logger = get_logger()

    async def handle_inbound(
        self, message: ChannelInboundMessage, now: datetime
    ) -> ChannelIngressReceipt:
        """Process one authenticated message exactly once at each owned boundary."""

        started_at = perf_counter()
        message, now = self._validate_inbound(message, now, started_at)

        try:
            binding = self._validated(
                await self._binding_repository.reserve(message.identity_hmac, now),
                ChannelBindingReservation,
            )
        except Exception:
            self._raise_unavailable(message, started_at)

        self._log(
            "channel_binding",
            message,
            status=binding.status.value,
            duration_ms=self._duration_ms(started_at),
        )
        if binding.status is ChannelBindingReservationStatus.PROCESSING:
            return self._receipt(message, ChannelIngressStatus.PROCESSING, started_at)
        if binding.status is ChannelBindingReservationStatus.FAILED:
            return self._receipt(message, ChannelIngressStatus.TERMINAL_NO_RETRY, started_at)

        if binding.status is ChannelBindingReservationStatus.RESERVED:
            binding = await self._activate_binding(binding, message, now, started_at)
        elif binding.status is not ChannelBindingReservationStatus.ACTIVE:
            self._raise_unavailable(message, started_at)

        conversation_id = binding.conversation_id
        if conversation_id is None:
            self._raise_unavailable(message, started_at)

        request = ConversationRequest(
            conversation_id=conversation_id,
            delivery_id=message.delivery_hmac,
            text=message.text,
        )
        try:
            result = self._validated(
                await self._conversation.respond(request, now), ConversationResult
            )
        except ConversationError as error:
            return self._conversation_error_receipt(message, error, started_at)
        except Exception:
            self._raise_unavailable(message, started_at)

        if result.conversation_id != conversation_id:
            self._raise_unavailable(message, started_at)
        self._log(
            "channel_inbound",
            message,
            status=result.status.value,
            duplicate=result.duplicate,
            duration_ms=self._duration_ms(started_at),
        )
        if result.status is ConversationExchangeStatus.PROCESSING:
            return self._receipt(message, ChannelIngressStatus.PROCESSING, started_at)
        if result.status is not ConversationExchangeStatus.COMPLETED or result.chat is None:
            return self._receipt(message, ChannelIngressStatus.TERMINAL_NO_RETRY, started_at)

        try:
            formatted = self._validated(self._formatter.format(result.chat), ChannelFormattedReply)
            outbound = ChannelOutboundMessage(
                identity_hmac=message.identity_hmac,
                delivery_hmac=message.delivery_hmac,
                exchange_id=result.exchange_id,
                text=formatted.text,
                citation_count=formatted.citation_count,
            )
        except ChannelError:
            self._raise_unavailable(message, started_at)
        except Exception:
            self._raise_unavailable(message, started_at)

        try:
            reservation = self._validated(
                await self._outbound_repository.reserve(binding.binding_id, outbound, now),
                ChannelOutboundReservation,
            )
        except Exception:
            self._raise_unavailable(message, started_at)

        if not self._matches_outbound(reservation, binding.binding_id, result.exchange_id):
            self._raise_unavailable(message, started_at)
        self._log(
            "channel_outbound",
            message,
            status=reservation.status.value,
            duplicate=result.duplicate,
            citation_count=formatted.citation_count,
            duration_ms=self._duration_ms(started_at),
        )
        if reservation.status is ChannelOutboundReservationStatus.SENT:
            return self._receipt(message, ChannelIngressStatus.ACKNOWLEDGED, started_at)
        if reservation.status is not ChannelOutboundReservationStatus.RESERVED:
            return self._receipt(message, ChannelIngressStatus.TERMINAL_NO_RETRY, started_at)

        try:
            sending = self._validated(
                await self._outbound_repository.mark_sending(reservation, now),
                ChannelOutboundReservation,
            )
        except Exception:
            self._raise_unavailable(message, started_at)

        if not self._matches_outbound(sending, binding.binding_id, result.exchange_id):
            self._raise_unavailable(message, started_at)
        if sending.status is not ChannelOutboundReservationStatus.SENDING:
            return self._receipt(message, ChannelIngressStatus.TERMINAL_NO_RETRY, started_at)

        receipt = await self._send_once(outbound)
        self._log(
            "channel_outbound",
            message,
            status=sending.status.value,
            delivery_status=receipt.status.value,
            duplicate=result.duplicate,
            citation_count=formatted.citation_count,
            duration_ms=self._duration_ms(started_at),
        )
        try:
            completed = self._validated(
                await self._outbound_repository.complete(sending, receipt, now),
                ChannelOutboundReservation,
            )
        except Exception:
            self._raise_unavailable(message, started_at)

        if not self._matches_outbound(completed, binding.binding_id, result.exchange_id):
            self._raise_unavailable(message, started_at)
        self._log(
            "channel_outbound",
            message,
            status=completed.status.value,
            delivery_status=receipt.status.value,
            duplicate=result.duplicate,
            citation_count=formatted.citation_count,
            duration_ms=self._duration_ms(started_at),
        )
        if completed.status is ChannelOutboundReservationStatus.SENT:
            return self._receipt(message, ChannelIngressStatus.ACKNOWLEDGED, started_at)
        return self._receipt(message, ChannelIngressStatus.TERMINAL_NO_RETRY, started_at)

    async def _activate_binding(
        self,
        reservation: ChannelBindingReservation,
        message: ChannelInboundMessage,
        now: datetime,
        started_at: float,
    ) -> ChannelBindingReservation:
        """Create and activate a reserved binding, failing it on every unsuccessful path."""

        try:
            created = self._validated(
                await self._conversation.create_conversation(now), CreateConversationResult
            )
            activated = self._validated(
                await self._binding_repository.activate(reservation, created.conversation_id, now),
                ChannelBindingReservation,
            )
            if (
                activated.binding_id != reservation.binding_id
                or activated.status is not ChannelBindingReservationStatus.ACTIVE
                or activated.conversation_id != created.conversation_id
            ):
                raise ValueError
        except Exception:
            try:
                await self._binding_repository.fail(
                    reservation, ChannelErrorCode.BINDING_ACTIVATION_FAILED.value, now
                )
            except Exception:
                pass
            self._raise_unavailable(message, started_at)
        self._log(
            "channel_binding",
            message,
            status=activated.status.value,
            duration_ms=self._duration_ms(started_at),
        )
        return activated

    async def _send_once(self, message: ChannelOutboundMessage) -> ChannelDeliveryReceipt:
        """Convert adapter failures or malformed results into one persistable terminal receipt."""

        try:
            value = await self._channel.send(message)
        except Exception:
            return ChannelDeliveryReceipt(
                status=ChannelDeliveryReceiptStatus.UNAVAILABLE,
                safe_error_code=ChannelErrorCode.BRIDGE_UNAVAILABLE.value,
                duration_ms=0,
            )
        try:
            return self._validated(value, ChannelDeliveryReceipt)
        except Exception:
            return ChannelDeliveryReceipt(
                status=ChannelDeliveryReceiptStatus.INVALID_RESPONSE,
                safe_error_code=ChannelErrorCode.INVALID_RESPONSE.value,
                duration_ms=0,
            )

    def _conversation_error_receipt(
        self,
        message: ChannelInboundMessage,
        error: ConversationError,
        started_at: float,
    ) -> ChannelIngressReceipt:
        if error.code in {ConversationErrorCode.BUSY, ConversationErrorCode.IN_PROGRESS}:
            return self._receipt(message, ChannelIngressStatus.PROCESSING, started_at)
        if error.code in {
            ConversationErrorCode.LEASE_EXPIRED,
            ConversationErrorCode.EXPIRED,
            ConversationErrorCode.NOT_FOUND,
            ConversationErrorCode.CONFLICT,
            ConversationErrorCode.DELIVERY_INVALID,
            ConversationErrorCode.STATE_INVALID,
        }:
            return self._receipt(message, ChannelIngressStatus.TERMINAL_NO_RETRY, started_at)
        self._raise_unavailable(message, started_at, error.code.value)

    def _validate_inbound(
        self, message: ChannelInboundMessage, now: datetime, started_at: float
    ) -> tuple[ChannelInboundMessage, datetime]:
        try:
            validated_message = self._validated(message, ChannelInboundMessage)
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError
            return validated_message, now
        except Exception:
            self._log(
                "channel_failed",
                message if isinstance(message, ChannelInboundMessage) else None,
                error_code=ChannelErrorCode.CHANNEL_MALFORMED.value,
                duration_ms=self._duration_ms(started_at),
            )
            raise ChannelError(ChannelErrorCode.CHANNEL_MALFORMED) from None

    def _receipt(
        self,
        message: ChannelInboundMessage,
        status: ChannelIngressStatus,
        started_at: float,
    ) -> ChannelIngressReceipt:
        self._log(
            "channel_inbound",
            message,
            ingress_status=status.value,
            duration_ms=self._duration_ms(started_at),
        )
        return ChannelIngressReceipt(status=status)

    def _raise_unavailable(
        self,
        message: ChannelInboundMessage,
        started_at: float,
        error_code: str = ChannelErrorCode.CHANNEL_UNAVAILABLE.value,
    ) -> NoReturn:
        self._log(
            "channel_failed",
            message,
            error_code=error_code,
            duration_ms=self._duration_ms(started_at),
        )
        raise ChannelError(ChannelErrorCode.CHANNEL_UNAVAILABLE) from None

    @staticmethod
    def _validated(value: object, model_type: type[_Model]) -> _Model:
        if not isinstance(value, model_type):
            raise ValueError
        if model_type is ChannelBindingReservation:
            ChannelService._validate_binding_reservation(cast(ChannelBindingReservation, value))
            return cast(_Model, value)
        model_class: Any = model_type
        model_value: Any = value
        return cast(_Model, model_class.model_validate(model_value.model_dump()))

    @staticmethod
    def _validate_binding_reservation(value: ChannelBindingReservation) -> None:
        """Validate binding port output without re-triggering its optional-time validator."""

        if not isinstance(value.binding_id, UUID):
            raise ValueError
        if value.status is ChannelBindingReservationStatus.ACTIVE:
            if not isinstance(value.conversation_id, UUID) or value.lease_expires_at is not None:
                raise ValueError
            return
        if value.status is ChannelBindingReservationStatus.RESERVED:
            if value.conversation_id is not None or not ChannelService._aware(
                value.lease_expires_at
            ):
                raise ValueError
            return
        if value.status is ChannelBindingReservationStatus.PROCESSING:
            if value.conversation_id is not None:
                raise ValueError
            if value.lease_expires_at is not None and not ChannelService._aware(
                value.lease_expires_at
            ):
                raise ValueError
            return
        if value.status is not ChannelBindingReservationStatus.FAILED:
            raise ValueError
        if value.conversation_id is not None or value.lease_expires_at is not None:
            raise ValueError

    @staticmethod
    def _aware(value: object) -> bool:
        return (
            isinstance(value, datetime)
            and value.tzinfo is not None
            and value.utcoffset() is not None
        )

    @staticmethod
    def _matches_outbound(
        reservation: ChannelOutboundReservation, binding_id: object, exchange_id: object
    ) -> bool:
        return reservation.binding_id == binding_id and reservation.exchange_id == exchange_id

    def _log(
        self,
        event: str,
        message: ChannelInboundMessage | None,
        *,
        status: str | None = None,
        ingress_status: str | None = None,
        delivery_status: str | None = None,
        duplicate: bool | None = None,
        citation_count: int | None = None,
        error_code: str | None = None,
        duration_ms: float | None = None,
        outcome: str | None = None,
    ) -> None:
        self._logger.info(
            event,
            extra={
                "channel_kind": message.channel.value if message is not None else None,
                "channel_status": status,
                "channel_ingress_status": ingress_status,
                "channel_delivery_status": delivery_status,
                "channel_duplicate": duplicate,
                "channel_citation_count": citation_count,
                "channel_error_code": error_code,
                "duration_ms": duration_ms,
                "outcome": outcome,
            },
        )

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)
