"""Immutable, adapter-neutral contracts for the Official Zalo Bot boundary."""

import re
from datetime import datetime
from enum import StrEnum
from typing import Final, Literal
from unicodedata import category, normalize
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HMAC_HEX_LENGTH: Final = 64
INBOUND_TEXT_MAX_CHARS: Final = 4_000
OUTBOUND_TEXT_MAX_CHARS: Final = 1_994
MAX_BODY_BYTES: Final = 65_536
AUTH_SKEW_SECONDS: Final = 300
BINDING_LEASE_SECONDS: Final = 120
OUTBOUND_MAX_ATTEMPTS: Final = 1

_LOWERCASE_HMAC: Final = re.compile(rf"[0-9a-f]{{{HMAC_HEX_LENGTH}}}")
_SAFE_ERROR_CODE: Final = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


class _FrozenChannelModel(BaseModel):
    """Value contracts which reject unknown fields without echoing untrusted values."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ChannelKind(StrEnum):
    """The only channel admitted by this demo."""

    ZALO_OFFICIAL_BOT = "ZALO_OFFICIAL_BOT"


class ChannelBindingStatus(StrEnum):
    """Durable lifecycle states of an identity-to-conversation binding."""

    BINDING = "BINDING"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"


class ChannelOutboundStatus(StrEnum):
    """Durable lifecycle states of one outbound bot delivery."""

    PENDING = "PENDING"
    SENDING = "SENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    ABANDONED = "ABANDONED"


class ChannelDeliveryReceiptStatus(StrEnum):
    """Normalized bot delivery outcomes, free of provider response data."""

    SENT = "SENT"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_RESPONSE = "INVALID_RESPONSE"


class ChannelIngressStatus(StrEnum):
    """Safe outcomes returned after an authenticated inbound event is handled."""

    ACKNOWLEDGED = "ACKNOWLEDGED"
    PROCESSING = "PROCESSING"
    TERMINAL_NO_RETRY = "TERMINAL_NO_RETRY"


class ChannelBindingReservationStatus(StrEnum):
    """Bounded outcomes returned while reserving an identity binding."""

    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


class ChannelOutboundReservationStatus(StrEnum):
    """Bounded outcomes returned while reserving an outbound delivery."""

    RESERVED = "RESERVED"
    SENDING = "SENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    ABANDONED = "ABANDONED"


def _normalize_safe_text(value: object, *, field_name: str) -> object:
    """NFC-normalize, trim, and reject blank or control-bearing text."""

    if not isinstance(value, str):
        return value
    normalized = normalize("NFC", value).strip()
    if not normalized or any(category(character).startswith("C") for character in normalized):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _normalize_formatted_reply_text(value: object) -> object:
    """Normalize rendered output while allowing the formatter's deliberate line breaks."""

    if not isinstance(value, str):
        return value
    normalized = normalize("NFC", value).strip()
    if not normalized or any(
        category(character).startswith("C") and character != "\n" for character in normalized
    ):
        raise ValueError("formatted reply text is invalid")
    return normalized


def _timezone_aware(value: datetime) -> datetime:
    """Require an explicit instant rather than a server-local wall-clock value."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def _lowercase_hmac(value: object) -> object:
    if not isinstance(value, str) or _LOWERCASE_HMAC.fullmatch(value) is None:
        raise ValueError("HMAC is invalid")
    return value


class ChannelInboundMessage(_FrozenChannelModel):
    """One authenticated, bounded Official Bot message after payload parsing."""

    channel: Literal[ChannelKind.ZALO_OFFICIAL_BOT] = ChannelKind.ZALO_OFFICIAL_BOT
    identity_hmac: str = Field(pattern=rf"^[0-9a-f]{{{HMAC_HEX_LENGTH}}}$")
    delivery_hmac: str = Field(pattern=rf"^[0-9a-f]{{{HMAC_HEX_LENGTH}}}$")
    text: str = Field(max_length=INBOUND_TEXT_MAX_CHARS)
    received_at: datetime

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return _normalize_formatted_reply_text(value)

    _validate_hmacs = field_validator("identity_hmac", "delivery_hmac", mode="before")(
        _lowercase_hmac
    )
    _validate_received_at = field_validator("received_at")(_timezone_aware)


class ChannelOutboundMessage(_FrozenChannelModel):
    """One bounded outbound message keyed by the authenticated inbound delivery HMAC."""

    channel: Literal[ChannelKind.ZALO_OFFICIAL_BOT] = ChannelKind.ZALO_OFFICIAL_BOT
    identity_hmac: str = Field(pattern=rf"^[0-9a-f]{{{HMAC_HEX_LENGTH}}}$")
    delivery_hmac: str = Field(pattern=rf"^[0-9a-f]{{{HMAC_HEX_LENGTH}}}$")
    exchange_id: UUID
    text: str = Field(max_length=OUTBOUND_TEXT_MAX_CHARS)
    citation_count: int = Field(ge=0, le=6)

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return _normalize_formatted_reply_text(value)

    _validate_hmacs = field_validator("identity_hmac", "delivery_hmac", mode="before")(
        _lowercase_hmac
    )


class ChannelDeliveryReceipt(_FrozenChannelModel):
    """Safe terminal result returned by a channel adapter for one send attempt."""

    status: ChannelDeliveryReceiptStatus
    safe_error_code: str | None = Field(default=None, max_length=64)
    duration_ms: float = Field(ge=0)

    @field_validator("safe_error_code")
    @classmethod
    def validate_safe_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _SAFE_ERROR_CODE.fullmatch(value) is None:
            raise ValueError("safe error code is invalid")
        return value

    @model_validator(mode="after")
    def validate_receipt_shape(self) -> "ChannelDeliveryReceipt":
        if self.status is ChannelDeliveryReceiptStatus.SENT:
            if self.safe_error_code is not None:
                raise ValueError("sent receipt must not include an error code")
        elif self.safe_error_code is None:
            raise ValueError("non-sent receipt requires an error code")
        return self


class ChannelIngressReceipt(_FrozenChannelModel):
    """Code-only acknowledgement for one authenticated bot event."""

    status: ChannelIngressStatus


class ChannelBindingReservation(_FrozenChannelModel):
    """Opaque binding reservation result for a future persistence adapter."""

    binding_id: UUID
    status: ChannelBindingReservationStatus
    conversation_id: UUID | None = None
    lease_expires_at: datetime | None = None

    _validate_lease_expires_at = field_validator("lease_expires_at")(_timezone_aware)

    @model_validator(mode="after")
    def validate_binding_shape(self) -> "ChannelBindingReservation":
        if self.status is ChannelBindingReservationStatus.RESERVED:
            if self.lease_expires_at is None:
                raise ValueError("reserved binding reservation requires a lease expiry")
            if self.conversation_id is not None:
                raise ValueError("reserved binding reservation must not include a conversation ID")
        elif self.status is ChannelBindingReservationStatus.PROCESSING:
            if self.conversation_id is not None:
                raise ValueError(
                    "processing binding reservation must not include a conversation ID"
                )
        elif self.status is ChannelBindingReservationStatus.ACTIVE:
            if self.conversation_id is None:
                raise ValueError("active binding reservation requires a conversation ID")
            if self.lease_expires_at is not None:
                raise ValueError("active binding reservation must not include a lease expiry")
        elif self.conversation_id is not None or self.lease_expires_at is not None:
            raise ValueError(
                "failed binding reservation must not include a conversation ID or lease expiry"
            )
        return self


class ChannelOutboundReservation(_FrozenChannelModel):
    """Opaque outbound reservation result for a future persistence adapter."""

    outbound_id: UUID
    binding_id: UUID
    exchange_id: UUID
    status: ChannelOutboundReservationStatus
    attempt_count: int = Field(ge=0, le=OUTBOUND_MAX_ATTEMPTS)
    safe_error_code: str | None = Field(default=None, max_length=64)

    @field_validator("safe_error_code")
    @classmethod
    def validate_safe_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _SAFE_ERROR_CODE.fullmatch(value) is None:
            raise ValueError("safe error code is invalid")
        return value

    @model_validator(mode="after")
    def validate_outbound_shape(self) -> "ChannelOutboundReservation":
        if self.status is ChannelOutboundReservationStatus.RESERVED:
            if self.attempt_count != 0 or self.safe_error_code is not None:
                raise ValueError(
                    "reserved outbound reservation must have no attempts or error code"
                )
        elif self.status in {
            ChannelOutboundReservationStatus.SENDING,
            ChannelOutboundReservationStatus.PROCESSING,
            ChannelOutboundReservationStatus.SENT,
        }:
            if self.attempt_count != OUTBOUND_MAX_ATTEMPTS or self.safe_error_code is not None:
                raise ValueError("active or sent outbound reservation has an invalid attempt state")
        elif self.attempt_count != OUTBOUND_MAX_ATTEMPTS or self.safe_error_code is None:
            raise ValueError(
                "terminal failed outbound reservation requires one attempt and an error code"
            )
        return self


class ChannelFormattedReply(_FrozenChannelModel):
    """Bounded, server-rendered text ready for one channel delivery."""

    text: str = Field(max_length=OUTBOUND_TEXT_MAX_CHARS)
    citation_count: int = Field(ge=0, le=6)
    overflowed: bool

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        return _normalize_formatted_reply_text(value)

    @model_validator(mode="after")
    def validate_overflow_shape(self) -> "ChannelFormattedReply":
        if self.overflowed and self.citation_count != 0:
            raise ValueError("overflowed formatted reply must not include citations")
        return self
