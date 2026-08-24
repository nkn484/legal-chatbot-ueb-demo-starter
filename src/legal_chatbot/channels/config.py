"""Disabled-by-default configuration for the Official Zalo Bot Platform adapter."""

from unicodedata import category

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_chatbot.channels.models import (
    BINDING_LEASE_SECONDS,
    MAX_BODY_BYTES,
    OUTBOUND_TEXT_MAX_CHARS,
)

_TIMEOUT_MAX_SECONDS = 30.0
_SECRET_MAX_CHARS = 256
_PLACEHOLDER_MARKERS = (
    "<",
    ">",
    "placeholder",
    "set_privately",
    "not_in_git",
    "replace",
    "changeme",
    "example",
)


class ChannelSettings(BaseSettings):
    """Settings for the official Bot API; its origin and path are code-owned."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    enabled: bool = Field(default=False, validation_alias="CHANNEL_ENABLED")
    bot_token: SecretStr | None = Field(default=None, validation_alias="ZALO_OFFICIAL_BOT_TOKEN")
    webhook_secret: SecretStr | None = Field(
        default=None, validation_alias="ZALO_OFFICIAL_BOT_WEBHOOK_SECRET"
    )
    identity_hmac_key: SecretStr | None = Field(
        default=None, validation_alias="CHANNEL_IDENTITY_HMAC_KEY"
    )
    max_body_bytes: int = Field(
        default=MAX_BODY_BYTES,
        ge=1,
        le=MAX_BODY_BYTES,
        validation_alias=AliasChoices("CHANNEL_MAX_BODY_BYTES"),
    )
    max_outbound_chars: int = Field(
        default=OUTBOUND_TEXT_MAX_CHARS,
        ge=1,
        le=OUTBOUND_TEXT_MAX_CHARS,
        validation_alias=AliasChoices("CHANNEL_MAX_OUTBOUND_CHARS"),
    )
    outbound_max_attempts: int = Field(
        default=1,
        ge=1,
        le=1,
        validation_alias=AliasChoices("CHANNEL_OUTBOUND_MAX_ATTEMPTS"),
    )
    binding_lease_seconds: int = Field(
        default=BINDING_LEASE_SECONDS,
        ge=1,
        le=BINDING_LEASE_SECONDS,
        validation_alias=AliasChoices("CHANNEL_BINDING_LEASE_SECONDS"),
    )
    timeout_seconds: float = Field(
        default=_TIMEOUT_MAX_SECONDS,
        gt=0,
        le=_TIMEOUT_MAX_SECONDS,
        validation_alias=AliasChoices("CHANNEL_TIMEOUT_SECONDS"),
    )

    @field_validator("bot_token", "webhook_secret", "identity_hmac_key", mode="before")
    @classmethod
    def normalize_empty_secret(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_enabled_bot(self) -> "ChannelSettings":
        if not self.enabled:
            return self
        if (
            self.bot_token is None
            or self.webhook_secret is None
            or self.identity_hmac_key is None
            or not _safe_secret(self.bot_token, minimum=16)
            or not _safe_secret(self.webhook_secret, minimum=16)
            or not _safe_secret(self.identity_hmac_key, minimum=32)
            or len(
                {
                    self.bot_token.get_secret_value(),
                    self.webhook_secret.get_secret_value(),
                    self.identity_hmac_key.get_secret_value(),
                }
            )
            != 3
        ):
            raise ValueError("enabled channel configuration is invalid")
        return self


def _safe_secret(secret: SecretStr, *, minimum: int) -> bool:
    value = secret.get_secret_value()
    lowered = value.casefold()
    return (
        minimum <= len(value) <= _SECRET_MAX_CHARS
        and not any(
            character.isspace() or category(character).startswith("C") for character in value
        )
        and not any(marker in lowered for marker in _PLACEHOLDER_MARKERS)
    )
