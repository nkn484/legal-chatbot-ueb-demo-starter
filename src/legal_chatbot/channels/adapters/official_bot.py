"""One-shot Official Zalo Bot API adapter without SDK dependencies."""

import json
import time

import httpx

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.errors import ChannelError, ChannelErrorCode
from legal_chatbot.channels.models import (
    ChannelDeliveryReceipt,
    ChannelDeliveryReceiptStatus,
    ChannelOutboundMessage,
)
from legal_chatbot.channels.port import ChannelPort
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry

_API_ORIGIN = "https://bot-api.zaloplatforms.com"
_MAX_RESPONSE_BYTES = 4_096


class OfficialZaloBotChannelPort(ChannelPort):
    """Send one opaque outbound message through the fixed Official Bot endpoint."""

    def __init__(
        self,
        settings: ChannelSettings,
        registry: OfficialBotRecipientRegistry,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not settings.enabled or settings.bot_token is None:
            raise ChannelError(ChannelErrorCode.CONFIG_INVALID)
        self._settings = settings
        self._registry = registry
        token = settings.bot_token.get_secret_value()
        self._send_url = f"{_API_ORIGIN}/bot{token}/sendMessage"
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.timeout_seconds), trust_env=False, follow_redirects=False
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()

    async def send(self, message: ChannelOutboundMessage) -> ChannelDeliveryReceipt:
        started = time.perf_counter()
        chat_id = self._registry.resolve(message.identity_hmac)
        if chat_id is None:
            return self._receipt(
                ChannelDeliveryReceiptStatus.UNAVAILABLE, "BOT_RECIPIENT_UNAVAILABLE", started
            )
        body = json.dumps(
            {"chat_id": chat_id, "text": message.text}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        request = self._client.build_request(
            "POST", self._send_url, content=body, headers={"Content-Type": "application/json"}
        )
        try:
            response = await self._client.send(request, stream=True)
        except httpx.TimeoutException:
            return self._receipt(ChannelDeliveryReceiptStatus.TIMEOUT, "BOT_TIMEOUT", started)
        except httpx.TransportError:
            return self._receipt(
                ChannelDeliveryReceiptStatus.UNAVAILABLE, "BOT_UNAVAILABLE", started
            )
        try:
            if not response.is_success:
                return self._receipt(ChannelDeliveryReceiptStatus.REJECTED, "BOT_REJECTED", started)
            content = await self._read_bounded(response)
            if content is None:
                return self._receipt(
                    ChannelDeliveryReceiptStatus.INVALID_RESPONSE, "BOT_INVALID_RESPONSE", started
                )
            payload = json.loads(content)
            if not (
                isinstance(payload, dict)
                and payload.get("ok") is True
                and isinstance(payload.get("result"), dict)
                and isinstance(payload["result"].get("message_id"), (str, int))
                and not isinstance(payload["result"].get("message_id"), bool)
            ):
                return self._receipt(
                    ChannelDeliveryReceiptStatus.INVALID_RESPONSE, "BOT_INVALID_RESPONSE", started
                )
            return ChannelDeliveryReceipt(
                status=ChannelDeliveryReceiptStatus.SENT,
                duration_ms=max(0, (time.perf_counter() - started) * 1000),
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return self._receipt(
                ChannelDeliveryReceiptStatus.INVALID_RESPONSE, "BOT_INVALID_RESPONSE", started
            )
        finally:
            await response.aclose()

    @staticmethod
    async def _read_bounded(response: httpx.Response) -> bytes | None:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                return None
            content.extend(chunk)
        return bytes(content)

    @staticmethod
    def _receipt(
        status: ChannelDeliveryReceiptStatus, code: str, started: float
    ) -> ChannelDeliveryReceipt:
        return ChannelDeliveryReceipt(
            status=status,
            safe_error_code=code,
            duration_ms=max(0, (time.perf_counter() - started) * 1000),
        )
