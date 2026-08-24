"""Provider-neutral immutable request, result, and health contracts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderHealthStatus(StrEnum):
    """Provider availability states exposed by a health probe."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class ProviderErrorCode(StrEnum):
    """Stable provider error categories safe for callers and logs."""

    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    REQUEST_REJECTED = "request_rejected"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    MODEL_NOT_FOUND = "model_not_found"


class _FrozenProviderModel(BaseModel):
    model_config = ConfigDict(frozen=True)


def sanitize_request_id(value: str | None) -> str | None:
    """Return only compact printable-ASCII request IDs safe for logs and errors."""
    if value is None:
        return value
    if not value or len(value) > 128 or any(not "!" <= character <= "~" for character in value):
        return None
    return value


def _strict_optional_request_id(value: str | None) -> str | None:
    if value is not None and sanitize_request_id(value) is None:
        raise ValueError("request_id must be a safe ASCII identifier")
    return value


class GenerationRequest(_FrozenProviderModel):
    """Bounded text generation input sent to an adapter."""

    input_text: str = Field(min_length=1, max_length=262_144)
    max_output_tokens: int = Field(ge=1, le=4_096)


class GenerationResult(_FrozenProviderModel):
    """Adapter output normalized without provider-specific response objects."""

    text: str = Field(min_length=1, max_length=1_048_576)
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    duration_ms: float = Field(ge=0)

    _validate_request_id = field_validator("request_id")(_strict_optional_request_id)


class ProviderHealth(_FrozenProviderModel):
    """Normalized result of a provider health check."""

    status: ProviderHealthStatus
    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)
    duration_ms: float = Field(ge=0)
    error_code: ProviderErrorCode | None = None

    _validate_request_id = field_validator("request_id")(_strict_optional_request_id)
