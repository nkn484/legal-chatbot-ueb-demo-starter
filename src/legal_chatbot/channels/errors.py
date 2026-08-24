"""Code-only failures for the Official Zalo Bot boundary."""

from enum import StrEnum


class ChannelErrorCode(StrEnum):
    """Stable failure categories that never contain body, signature, or key data."""

    BODY_TOO_LARGE = "BODY_TOO_LARGE"
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_STALE = "AUTH_STALE"
    AUTH_MALFORMED = "AUTH_MALFORMED"
    CONFIG_INVALID = "CONFIG_INVALID"
    BINDING_BUSY = "BINDING_BUSY"
    BINDING_FAILED = "BINDING_FAILED"
    BINDING_ACTIVATION_FAILED = "BINDING_ACTIVATION_FAILED"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    OUTBOUND_STATE_INVALID = "OUTBOUND_STATE_INVALID"
    BRIDGE_UNAVAILABLE = "BRIDGE_UNAVAILABLE"
    CHANNEL_MALFORMED = "CHANNEL_MALFORMED"
    CHANNEL_UNAVAILABLE = "CHANNEL_UNAVAILABLE"
    CHANNEL_OVERFLOW = "CHANNEL_OVERFLOW"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"


class ChannelError(Exception):
    """A code-only exception safe to return to callers and emit in logs."""

    def __init__(self, code: ChannelErrorCode) -> None:
        self.code = code
        super().__init__(code.value)

    def __str__(self) -> str:
        return self.code.value
