"""Official Bot webhook authentication and opaque identity derivation."""

import hashlib
import hmac
from typing import Final, NamedTuple

from pydantic import SecretStr

from legal_chatbot.channels.errors import ChannelError, ChannelErrorCode

CHANNEL_JSON_MEDIA_TYPE: Final = "application/json"
BOT_SECRET_HEADER: Final = "X-Bot-Api-Secret-Token"
BODY_TOO_LARGE_RESPONSE_BODY: Final = b'{"error":{"code":"CHANNEL_BODY_TOO_LARGE"}}'
AUTH_FAILURE_RESPONSE_BODY: Final = b'{"error":{"code":"CHANNEL_AUTH_FAILED"}}'


class ChannelAuthFailureResponse(NamedTuple):
    status_code: int
    body: bytes
    content_type: str


BODY_TOO_LARGE_RESPONSE: Final = ChannelAuthFailureResponse(
    413, BODY_TOO_LARGE_RESPONSE_BODY, CHANNEL_JSON_MEDIA_TYPE
)
AUTH_FAILURE_RESPONSE: Final = ChannelAuthFailureResponse(
    401, AUTH_FAILURE_RESPONSE_BODY, CHANNEL_JSON_MEDIA_TYPE
)


def verify_bot_secret(secret: SecretStr | None, supplied: str | None) -> None:
    """Constant-time verify the official secret header without retaining its value."""

    if not isinstance(secret, SecretStr) or not isinstance(supplied, str):
        raise ChannelError(ChannelErrorCode.AUTH_INVALID)
    if not hmac.compare_digest(secret.get_secret_value(), supplied):
        raise ChannelError(ChannelErrorCode.AUTH_INVALID)


def identity_hmac(key: SecretStr, chat_id: object, sender_id: object) -> str:
    return _opaque_hmac(key, b"zalo-official-bot-v1:identity", chat_id, sender_id)


def delivery_hmac(key: SecretStr, chat_id: object, sender_id: object, message_id: object) -> str:
    return _opaque_hmac(key, b"zalo-official-bot-v1:delivery", chat_id, sender_id, message_id)


def _opaque_hmac(key: SecretStr, domain: bytes, *values: object) -> str:
    if not isinstance(key, SecretStr):
        raise ChannelError(ChannelErrorCode.AUTH_MALFORMED)
    encoded = tuple(_identifier(value) for value in values)
    material = (
        domain + b"\x00" + b"".join(len(value).to_bytes(4, "big") + value for value in encoded)
    )
    return hmac.new(key.get_secret_value().encode("utf-8"), material, hashlib.sha256).hexdigest()


def _identifier(value: object) -> bytes:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ChannelError(ChannelErrorCode.AUTH_MALFORMED)
    text = str(value)
    if not text or len(text) > 128 or any(ord(character) < 32 for character in text):
        raise ChannelError(ChannelErrorCode.AUTH_MALFORMED)
    return text.encode("utf-8")
