"""Pure async ports for Official Zalo Bot delivery, binding, and conversation use."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from legal_chatbot.channels.models import (
    ChannelBindingReservation,
    ChannelDeliveryReceipt,
    ChannelInboundMessage,
    ChannelIngressReceipt,
    ChannelOutboundMessage,
    ChannelOutboundReservation,
)
from legal_chatbot.conversation.models import (
    ConversationRequest,
    ConversationResult,
    CreateConversationResult,
)


class ChannelIngressPort(Protocol):
    """Handle one authenticated normalized inbound event through the channel service seam."""

    async def handle_inbound(
        self, message: ChannelInboundMessage, now: datetime
    ) -> ChannelIngressReceipt:
        """Return a bounded safe acknowledgement using an aware caller-clock timestamp."""
        ...


class ChannelPort(Protocol):
    """Send one bounded message through an isolated channel adapter."""

    async def send(self, message: ChannelOutboundMessage) -> ChannelDeliveryReceipt:
        """Return one normalized receipt without exposing channel SDK details."""
        ...

    async def aclose(self) -> None:
        """Release adapter-owned asynchronous resources."""
        ...


class ChannelConversationPort(Protocol):
    """Use the M07 conversation seam without importing its service implementation."""

    async def create_conversation(self, now: datetime) -> CreateConversationResult:
        """Create a conversation using an aware caller-clock timestamp."""
        ...

    async def respond(self, request: ConversationRequest, now: datetime) -> ConversationResult:
        """Process one M07 request using an aware caller-clock timestamp."""
        ...


class ChannelBindingRepositoryPort(Protocol):
    """Reserve an HMAC identity binding without ORM or session details."""

    async def reserve(self, identity_hmac: str, now: datetime) -> ChannelBindingReservation:
        """Reserve or observe one identity binding using an aware timestamp."""
        ...

    async def activate(
        self, reservation: ChannelBindingReservation, conversation_id: UUID, now: datetime
    ) -> ChannelBindingReservation:
        """Associate a reserved binding with one opaque conversation identity."""
        ...

    async def fail(
        self, reservation: ChannelBindingReservation, safe_error_code: str, now: datetime
    ) -> ChannelBindingReservation:
        """Mark one binding reservation as failed without retaining failure text."""
        ...


class ChannelOutboundRepositoryPort(Protocol):
    """Reserve one outbound send attempt without exposing persistence implementation."""

    async def reserve(
        self, binding_id: UUID, message: ChannelOutboundMessage, now: datetime
    ) -> ChannelOutboundReservation:
        """Reserve one bounded outbound delivery using an aware timestamp."""
        ...

    async def mark_sending(
        self, reservation: ChannelOutboundReservation, now: datetime
    ) -> ChannelOutboundReservation:
        """Mark the single permitted send attempt as in progress."""
        ...

    async def complete(
        self,
        reservation: ChannelOutboundReservation,
        receipt: ChannelDeliveryReceipt,
        now: datetime,
    ) -> ChannelOutboundReservation:
        """Persist the normalized delivery receipt using an aware timestamp."""
        ...
