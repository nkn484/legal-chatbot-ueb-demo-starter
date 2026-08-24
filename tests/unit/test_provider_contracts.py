"""M02 provider contract and registry tests without live provider adapters."""

import httpx
import pytest
from pydantic import ValidationError

from legal_chatbot.providers.adapters.shineshop import ShineShopAdapter
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    GenerationResult,
    ProviderErrorCode,
    ProviderHealth,
    ProviderHealthStatus,
    sanitize_request_id,
)
from legal_chatbot.providers.registry import ProviderRegistry, create_provider

SENTINEL_KEY = "provider-secret-sentinel"


def provider_settings(**overrides: object) -> ProviderSettings:
    """Create valid settings without relying on a local environment file."""
    values: dict[str, object] = {
        "LLM_BASE_URL": "https://api.example.test/v1",
        "LLM_MODEL": "demo-model",
        "LLM_API_KEY": SENTINEL_KEY,
    }
    values.update(overrides)
    return ProviderSettings(**values)


def test_provider_settings_aliases_defaults_and_secret_redaction() -> None:
    settings = provider_settings(LLM_API_KEY="preferred-key", SHINE_API_KEY=SENTINEL_KEY)
    assert settings.provider == "shineshop"
    assert settings.api_key.get_secret_value() == "preferred-key"
    assert settings.connect_timeout_seconds == 10
    assert settings.response_timeout_seconds == 60
    assert settings.max_input_chars == 65_536
    assert settings.max_output_tokens == 4_096
    assert settings.max_response_bytes == 1_048_576
    assert settings.health_max_attempts == 2
    assert settings.retry_after_max_seconds == 2
    assert "preferred-key" not in repr(settings)

    transitional = ProviderSettings(
        LLM_BASE_URL="https://api.example.test/v1",
        LLM_MODEL="demo-model",
        SHINE_API_KEY=SENTINEL_KEY,
    )
    assert transitional.api_key.get_secret_value() == SENTINEL_KEY

    direct = ProviderSettings(
        provider="shineshop",
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key=SENTINEL_KEY,
    )
    assert direct.model == "demo-model"


@pytest.mark.parametrize(
    "api_key",
    ["", " secret", "secret ", "secret value", "secret\nvalue", "<SET_PRIVATELY_NOT_IN_GIT>"],
)
def test_provider_settings_rejects_unsafe_or_placeholder_api_key_without_leakage(
    api_key: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        provider_settings(LLM_API_KEY=api_key)
    if api_key:
        assert api_key not in str(exc_info.value)
    assert "LLM_API_KEY must be a valid provider credential" in str(exc_info.value)


@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("http://api.example.test", "demo-model"),
        ("https://user@api.example.test", "demo-model"),
        ("https://api.example.test?query=value", "demo-model"),
        ("https://api.example.test#fragment", "demo-model"),
        ("https://api.example.test/path with space", "demo-model"),
        ("https://api.example.test/<PLACEHOLDER>", "demo-model"),
        ("https://api.example.test", "model name"),
        ("https://api.example.test", "<EXACT_MODEL_ID_FROM_SHINE_V1_MODELS>"),
    ],
)
def test_provider_settings_rejects_unsafe_url_or_model_without_secret_leakage(
    base_url: str, model: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        provider_settings(LLM_BASE_URL=base_url, LLM_MODEL=model)
    assert SENTINEL_KEY not in str(exc_info.value)


def test_models_are_immutable_and_bounded() -> None:
    request = GenerationRequest(input_text="question", max_output_tokens=1)
    result = GenerationResult(
        text="answer", provider="shineshop", model="demo-model", request_id="req-1", duration_ms=0
    )
    health = ProviderHealth(
        status=ProviderHealthStatus.HEALTHY,
        provider="shineshop",
        model="demo-model",
        duration_ms=0,
    )
    with pytest.raises(ValidationError):
        request.max_output_tokens = 2
    with pytest.raises(ValidationError):
        GenerationRequest(input_text="", max_output_tokens=1)
    with pytest.raises(ValidationError):
        GenerationRequest(input_text="question", max_output_tokens=4_097)
    with pytest.raises(ValidationError):
        GenerationResult(text="", provider="shineshop", model="demo-model", duration_ms=0)
    assert result.text == "answer"
    assert health.status is ProviderHealthStatus.HEALTHY
    assert health.request_id is None
    with pytest.raises(ValidationError):
        ProviderHealth(
            status=ProviderHealthStatus.HEALTHY,
            provider="shineshop",
            model="demo-model",
            request_id="unsafe id",
            duration_ms=0,
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("req-1", "req-1"),
        ("unsafe id", None),
        ("unsafe\nrequest", None),
        ("x" * 129, None),
    ],
)
def test_sanitize_request_id_allows_only_printable_ascii(
    value: str | None, expected: str | None
) -> None:
    assert sanitize_request_id(value) == expected


def test_provider_error_never_exposes_raw_text() -> None:
    error = ProviderError(
        ProviderErrorCode.RATE_LIMITED,
        retryable=True,
        status_code=429,
        request_id="req-1",
        retry_after_seconds=2,
    )
    assert str(error) == "rate_limited"
    assert error.code is ProviderErrorCode.RATE_LIMITED
    assert error.retryable is True
    assert error.status_code == 429
    assert error.request_id == "req-1"
    assert error.retry_after_seconds == 2
    assert "raw provider body" not in str(error)
    assert ProviderError(ProviderErrorCode.TIMEOUT, request_id="unsafe id").request_id is None


def test_registry_normalizes_names_and_rejects_duplicate_or_unknown() -> None:
    registry = ProviderRegistry()
    settings = provider_settings(LLM_PROVIDER="anthropic")
    created: list[tuple[ProviderSettings, object]] = []
    fake_provider = object()

    def anthropic_factory(configured_settings: ProviderSettings, client: object) -> object:
        created.append((configured_settings, client))
        return fake_provider

    registry.register("anthropic", anthropic_factory)  # type: ignore[arg-type]
    assert (
        create_provider(settings, registry=registry) is fake_provider  # type: ignore[comparison-overlap]
    )
    assert created == [(settings, None)]

    with pytest.raises(ProviderError) as duplicate:
        registry.register("ANTHROPIC", anthropic_factory)  # type: ignore[arg-type]
    assert duplicate.value.code is ProviderErrorCode.REQUEST_REJECTED

    with pytest.raises(ProviderError) as unknown:
        registry.create("unknown", settings)
    assert unknown.value.code is ProviderErrorCode.PROVIDER_NOT_CONFIGURED


def test_create_provider_rejects_anthropic_without_importing_an_sdk() -> None:
    with pytest.raises(ProviderError) as exc_info:
        create_provider(provider_settings(LLM_PROVIDER="anthropic"))
    assert exc_info.value.code is ProviderErrorCode.PROVIDER_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_default_registry_creates_shineshop_adapter_without_http() -> None:
    async with httpx.AsyncClient() as client:
        provider = create_provider(provider_settings(), client=client)
        assert isinstance(provider, ShineShopAdapter)
