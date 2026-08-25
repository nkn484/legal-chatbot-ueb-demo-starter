"""One-shot processing-status delivery through the existing channel sender."""

from __future__ import annotations

from uuid import uuid4

from legal_chatbot.channels.models import ChannelInboundMessage, ChannelOutboundMessage
from legal_chatbot.channels.port import ChannelPort
from legal_chatbot.legal_evidence.application import LegalChatApplication


class ChannelProcessingStatusNotifier:
    """Translate a channel-neutral processing status using the existing ChannelPort."""

    def __init__(self, channel: ChannelPort, application: LegalChatApplication) -> None:
        self._channel = channel
        self._application = application

    async def notify(self, message: ChannelInboundMessage) -> None:
        status = self._application.processing_status(message.delivery_hmac)
        await self._channel.send(
            ChannelOutboundMessage(
                identity_hmac=message.identity_hmac,
                delivery_hmac=message.delivery_hmac,
                exchange_id=uuid4(),
                text=status.message,
                citation_count=0,
            )
        )


__all__ = ["ChannelProcessingStatusNotifier"]
