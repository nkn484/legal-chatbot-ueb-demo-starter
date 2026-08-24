"""ASGI ingress boundary for authenticated Official Zalo Bot callbacks."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from fastapi import FastAPI, Request, Response
from pydantic import ValidationError

from legal_chatbot.channels.auth import (
    AUTH_FAILURE_RESPONSE,
    BODY_TOO_LARGE_RESPONSE,
    BOT_SECRET_HEADER,
    CHANNEL_JSON_MEDIA_TYPE,
    delivery_hmac,
    identity_hmac,
    verify_bot_secret,
)
from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.models import (
    ChannelInboundMessage,
    ChannelIngressReceipt,
    ChannelIngressStatus,
)
from legal_chatbot.channels.port import ChannelIngressPort
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry

OFFICIAL_BOT_WEBHOOK_PATH: Final = "/webhooks/zalo-bot"
_OK_BODY: Final = b'{"status":"ok"}'
_MALFORMED_BODY: Final = b'{"error":{"code":"CHANNEL_MALFORMED"}}'
_UNAVAILABLE_BODY: Final = b'{"error":{"code":"CHANNEL_UNAVAILABLE"}}'
_TEXT_EVENT: Final = "message.text.received"
_UNSUPPORTED_EVENT: Final = "message.unsupported.received"
_MAX_DATE_MILLISECONDS: Final = 4_102_444_800_000


class _BodyTooLarge(Exception):
    pass


def _aware_utc_now() -> datetime:
    return datetime.now(UTC)


async def _read_bounded_body(request: Request, maximum: int) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > maximum:
            raise _BodyTooLarge
        body.extend(chunk)
    return bytes(body)


def _single_header(request: Request, name: str) -> str | None:
    expected = name.encode("ascii").lower()
    values = [value for key, value in request.scope["headers"] if key.lower() == expected]
    return values[0].decode("latin-1") if len(values) == 1 else None


def _response(status: int, body: bytes) -> Response:
    return Response(status_code=status, content=body, media_type=CHANNEL_JSON_MEDIA_TYPE)


def _is_json_media_type(value: str | None) -> bool:
    return (
        value is not None and value.split(";", 1)[0].strip().casefold() == CHANNEL_JSON_MEDIA_TYPE
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _parse_event(
    body: bytes, settings: ChannelSettings, now: datetime
) -> tuple[ChannelInboundMessage, str | int] | None:
    payload = json.loads(
        body.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError
    event_name, message = _event_parts(payload)
    if event_name != _TEXT_EVENT:
        return None
    if not isinstance(message, dict):
        raise ValueError
    chat, sender = message.get("chat"), message.get("from")
    if not isinstance(chat, dict) or not isinstance(sender, dict):
        raise ValueError
    chat_id, sender_id, message_id = chat.get("id"), sender.get("id"), message.get("message_id")
    if (
        chat.get("chat_type") != "PRIVATE"
        or sender.get("is_bot") is not False
        or not isinstance(message.get("text"), str)
    ):
        return None
    if (
        isinstance(chat_id, bool)
        or not isinstance(chat_id, (str, int))
        or isinstance(sender_id, bool)
        or not isinstance(sender_id, (str, int))
        or isinstance(message_id, bool)
        or not isinstance(message_id, (str, int))
    ):
        raise ValueError
    key = settings.identity_hmac_key
    if key is None:
        raise ValueError
    received_at = _message_time(message.get("date"), now)
    return (
        ChannelInboundMessage(
            identity_hmac=identity_hmac(key, chat_id, sender_id),
            delivery_hmac=delivery_hmac(key, chat_id, sender_id, message_id),
            text=message["text"],
            received_at=received_at,
        ),
        chat_id,
    )


def _event_parts(payload: dict[str, object]) -> tuple[object, object]:
    """Accept the documented ``ok/result`` envelope and M00's measured direct envelope."""

    result = payload.get("result")
    if payload.get("ok") is True and isinstance(result, dict):
        return result.get("event_name"), result.get("message")
    return payload.get("event_name"), payload.get("message")


def _reject_constant(_value: str) -> None:
    raise ValueError


def _message_time(value: object, fallback: datetime) -> datetime:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 0 < value <= _MAX_DATE_MILLISECONDS
    ):
        return fallback
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except (OverflowError, OSError, ValueError):
        return fallback


def _valid_receipt(value: object) -> bool:
    if not isinstance(value, ChannelIngressReceipt):
        return False
    try:
        return ChannelIngressReceipt.model_validate(value.model_dump()).status in set(
            ChannelIngressStatus
        )
    except ValidationError:
        return False


def install_official_bot_webhook(
    app: FastAPI,
    service: ChannelIngressPort,
    settings: ChannelSettings,
    recipients: OfficialBotRecipientRegistry,
    clock: Callable[[], datetime] = _aware_utc_now,
) -> None:
    """Install the public Official Bot callback; raw IDs remain at this boundary."""

    @app.post(OFFICIAL_BOT_WEBHOOK_PATH)
    async def receive_event(request: Request) -> Response:
        try:
            body = await _read_bounded_body(request, settings.max_body_bytes)
        except _BodyTooLarge:
            return _response(BODY_TOO_LARGE_RESPONSE.status_code, BODY_TOO_LARGE_RESPONSE.body)
        except Exception:
            return _response(503, _UNAVAILABLE_BODY)
        try:
            verify_bot_secret(settings.webhook_secret, _single_header(request, BOT_SECRET_HEADER))
        except Exception:
            return _response(AUTH_FAILURE_RESPONSE.status_code, AUTH_FAILURE_RESPONSE.body)
        if not _is_json_media_type(_single_header(request, "Content-Type")):
            return _response(400, _MALFORMED_BODY)
        now = clock()
        try:
            parsed = _parse_event(body, settings, now)
        except Exception:
            return _response(400, _MALFORMED_BODY)
        if parsed is None:
            return _response(200, _OK_BODY)
        message, chat_id = parsed
        recipients.remember(message.identity_hmac, chat_id)
        try:
            receipt = await service.handle_inbound(message, now)
            if not _valid_receipt(receipt):
                return _response(503, _UNAVAILABLE_BODY)
        except Exception:
            return _response(503, _UNAVAILABLE_BODY)
        return _response(200, _OK_BODY)
