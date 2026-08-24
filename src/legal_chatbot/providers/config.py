"""Validated configuration shared by all LLM provider adapters."""

from typing import Literal
from unicodedata import category
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_API_KEY_ERROR = "LLM_API_KEY must be a valid provider credential"
_BASE_URL_ERROR = "LLM_BASE_URL must be a valid HTTPS provider URL"
_MODEL_ERROR = "LLM_MODEL must be a valid provider model identifier"
_API_KEY_PLACEHOLDER = "<SET_PRIVATELY_NOT_IN_GIT>"
_MODEL_PLACEHOLDER = "<EXACT_MODEL_ID_FROM_SHINE_V1_MODELS>"


def _has_whitespace_or_control(value: str) -> bool:
    return any(character.isspace() or category(character).startswith("C") for character in value)


class ProviderSettings(BaseSettings):
    """Provider settings with bounded limits and redacted credentials."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    provider: Literal["shineshop", "anthropic"] = Field(
        default="shineshop", validation_alias="LLM_PROVIDER"
    )
    base_url: str = Field(validation_alias="LLM_BASE_URL")
    model: str = Field(validation_alias="LLM_MODEL")
    api_key: SecretStr = Field(
        repr=False,
        validation_alias=AliasChoices("LLM_API_KEY", "SHINE_API_KEY"),
    )
    connect_timeout_seconds: float = Field(
        default=10.0, ge=0.1, le=60.0, validation_alias="LLM_CONNECT_TIMEOUT_SECONDS"
    )
    response_timeout_seconds: float = Field(
        default=60.0, ge=1.0, le=300.0, validation_alias="LLM_RESPONSE_TIMEOUT_SECONDS"
    )
    max_input_chars: int = Field(
        default=65_536, ge=1, le=262_144, validation_alias="LLM_MAX_INPUT_CHARS"
    )
    max_output_tokens: int = Field(
        default=4_096, ge=1, le=4_096, validation_alias="LLM_MAX_OUTPUT_TOKENS"
    )
    max_response_bytes: int = Field(
        default=1_048_576, ge=1_024, le=10_485_760, validation_alias="LLM_MAX_RESPONSE_BYTES"
    )
    health_max_attempts: int = Field(
        default=2, ge=1, le=3, validation_alias="LLM_HEALTH_MAX_ATTEMPTS"
    )
    retry_after_max_seconds: float = Field(
        default=2.0, ge=0.0, le=60.0, validation_alias="LLM_RETRY_AFTER_MAX_SECONDS"
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        """Permit HTTPS provider endpoints and optional base paths only."""
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise ValueError(_BASE_URL_ERROR) from None
        if (
            _has_whitespace_or_control(value)
            or "<" in value
            or ">" in value
            or parsed.scheme != "https"
            or not parsed.hostname
            or "@" in parsed.netloc
            or parsed.query
            or parsed.fragment
            or port is not None
            and not 1 <= port <= 65535
        ):
            raise ValueError(_BASE_URL_ERROR)
        return value

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        """Fail closed for empty, placeholder, or ambiguous credentials."""
        secret = value.get_secret_value()
        if (
            not secret
            or len(secret) > 4_096
            or _has_whitespace_or_control(secret)
            or secret == _API_KEY_PLACEHOLDER
        ):
            raise ValueError(_API_KEY_ERROR)
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        """Reject ambiguous model names before an adapter sends a request."""
        if (
            not value
            or len(value) > 128
            or _has_whitespace_or_control(value)
            or value == _MODEL_PLACEHOLDER
            or "<" in value
            or ">" in value
        ):
            raise ValueError(_MODEL_ERROR)
        return value
