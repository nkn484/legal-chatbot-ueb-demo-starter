"""Unit tests for the bounded SHINE SHOP adapter."""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from legal_chatbot.providers.adapters.shineshop import ShineShopAdapter
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    ProviderErrorCode,
    ProviderHealthStatus,
)

SENTINEL_KEY = "sentinel-shine-api-key"
SENTINEL_INPUT = "sentinel-private-input"
SENTINEL_OUTPUT = "sentinel-private-output"
SENTINEL_BODY = "sentinel-provider-error-body"


def settings(**overrides: object) -> ProviderSettings:
    values: dict[str, object] = {
        "provider": "shineshop",
        "base_url": "https://api.example.test/v1",
        "model": "model-a",
        "api_key": SENTINEL_KEY,
        "connect_timeout_seconds": 1.0,
        "response_timeout_seconds": 2.0,
        "max_input_chars": 100,
        "max_output_tokens": 20,
        "max_response_bytes": 1024,
        "health_max_attempts": 3,
        "retry_after_max_seconds": 4.0,
    }
    values.update(overrides)
    return ProviderSettings(**values)


def request(input_text: str = "hello", max_output_tokens: int = 5) -> GenerationRequest:
    return GenerationRequest(input_text=input_text, max_output_tokens=max_output_tokens)


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.example.test/v1/"
    )


@pytest.mark.asyncio
async def test_generate_posts_one_relative_response_request_and_extracts_text() -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(
            200,
            headers={"x-request-id": "req-1"},
            json={
                "usage": {"output_tokens": 7},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "READY"},
                            {"type": "refusal", "refusal": "ignored"},
                        ],
                    }
                ]
            },
        )

    async with client(handler) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client).generate(request())

    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert str(calls[0].url) == "https://api.example.test/v1/responses"
    assert json.loads(calls[0].content) == {
        "model": "model-a",
        "input": "hello",
        "max_output_tokens": 5,
        "stream": False,
    }
    assert result.text == "READY"
    assert result.provider == "shineshop"
    assert result.model == "model-a"
    assert result.request_id == "req-1"
    assert result.duration_ms >= 0
    assert result.output_tokens == 7


@pytest.mark.asyncio
async def test_generate_discards_unsafe_request_id() -> None:
    async with client(
        lambda _: httpx.Response(
            200,
            headers={"x-request-id": "unsafe id"},
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "READY"}],
                    }
                ]
            },
        )
    ) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client).generate(request())

    assert result.request_id is None


@pytest.mark.asyncio
async def test_owned_client_is_private_and_only_owned_client_is_closed() -> None:
    owned = ShineShopAdapter(settings(base_url="https://api.example.test/v1/"))
    assert owned._client._trust_env is False  # noqa: SLF001 - construction safety assertion
    assert str(owned._client.base_url) == "https://api.example.test/v1/"
    assert "content-type" not in owned._client.headers
    await owned.aclose()
    assert owned._client.is_closed  # noqa: SLF001 - construction safety assertion

    async with client(lambda _: httpx.Response(200, json={"data": []})) as injected:
        adapter = ShineShopAdapter(settings(), client=injected)
        await adapter.aclose()
        assert not injected.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_text", "output_tokens"),
    [("x" * 101, 5), ("hello", 21)],
)
async def test_generate_rejects_config_bound_violations_before_http(
    input_text: str, output_tokens: int
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        with pytest.raises(ProviderError) as raised:
            await ShineShopAdapter(settings(), client=http_client).generate(
                request(input_text, output_tokens)
            )

    assert raised.value.code is ProviderErrorCode.REQUEST_REJECTED
    assert raised.value.retryable is False
    assert raised.value.status_code is None
    assert raised.value.request_id is None
    assert calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected", "retryable"),
    [
        (401, ProviderErrorCode.AUTHENTICATION_FAILED, False),
        (403, ProviderErrorCode.AUTHENTICATION_FAILED, False),
        (400, ProviderErrorCode.REQUEST_REJECTED, False),
        (404, ProviderErrorCode.REQUEST_REJECTED, False),
        (413, ProviderErrorCode.REQUEST_REJECTED, False),
        (408, ProviderErrorCode.TIMEOUT, True),
        (500, ProviderErrorCode.UNAVAILABLE, True),
        (502, ProviderErrorCode.UNAVAILABLE, True),
        (503, ProviderErrorCode.UNAVAILABLE, True),
        (504, ProviderErrorCode.UNAVAILABLE, True),
    ],
)
async def test_generate_maps_statuses_without_retries(
    status: int, expected: ProviderErrorCode, retryable: bool
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"x-request-id": "req-status"})

    async with client(handler) as http_client:
        with pytest.raises(ProviderError) as raised:
            await ShineShopAdapter(settings(), client=http_client).generate(request())

    assert raised.value.code is expected
    assert raised.value.retryable is retryable
    assert raised.value.status_code == status
    assert raised.value.request_id == "req-status"
    assert calls == 1


@pytest.mark.asyncio
async def test_generate_maps_retry_after_and_stable_model_not_found() -> None:
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "999", "x-request-id": "req-rate"}),
            httpx.Response(
                404,
                headers={"x-request-id": "req-model"},
                json={"error": {"code": "model_not_found"}},
            ),
        ]
    )

    async with client(lambda _: next(responses)) as http_client:
        adapter = ShineShopAdapter(settings(), client=http_client)
        with pytest.raises(ProviderError) as limited:
            await adapter.generate(request())
        with pytest.raises(ProviderError) as missing:
            await adapter.generate(request())

    assert limited.value.code is ProviderErrorCode.RATE_LIMITED
    assert limited.value.retryable is True
    assert limited.value.status_code == 429
    assert limited.value.request_id == "req-rate"
    assert limited.value.retry_after_seconds == 4.0
    assert missing.value.code is ProviderErrorCode.MODEL_NOT_FOUND
    assert missing.value.status_code == 404
    assert missing.value.request_id == "req-model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, headers={"x-request-id": "req-invalid"}, content=b"{"),
        httpx.Response(200, headers={"x-request-id": "req-invalid"}, json={"output": []}),
        httpx.Response(200, headers={"x-request-id": "req-invalid"}, content=b"x" * 1025),
    ],
)
async def test_generate_rejects_invalid_empty_and_oversized_responses(
    response: httpx.Response,
) -> None:
    async with client(lambda _: response) as http_client:
        with pytest.raises(ProviderError) as raised:
            await ShineShopAdapter(settings(), client=http_client).generate(request())

    assert raised.value.code is ProviderErrorCode.INVALID_RESPONSE
    assert raised.value.status_code == 200
    assert raised.value.request_id == "req-invalid"


@pytest.mark.asyncio
async def test_health_retries_only_safe_get_failures_and_requires_exact_model() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert http_request.method == "GET"
        assert str(http_request.url) == "https://api.example.test/v1/models"
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": "99"})
        return httpx.Response(
            200,
            headers={"x-request-id": "req-health"},
            json={"data": [{"id": "model-a"}]},
        )

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with client(handler) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client, sleep=sleep).health_check()

    assert calls == 2
    assert sleeps == [4.0]
    assert result.status is ProviderHealthStatus.HEALTHY
    assert result.error_code is None
    assert result.request_id == "req-health"


@pytest.mark.asyncio
async def test_health_clamps_future_http_date_retry_after() -> None:
    calls = 0
    sleeps: list[float] = []
    future = format_datetime(datetime.now(UTC) + timedelta(days=1), usegmt=True)

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, headers={"Retry-After": future})
        return httpx.Response(200, json={"data": [{"id": "model-a"}]})

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with client(handler) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client, sleep=sleep).health_check()

    assert result.status is ProviderHealthStatus.HEALTHY
    assert calls == 2
    assert sleeps == [4.0]


@pytest.mark.asyncio
async def test_health_returns_normalized_unhealthy_results_without_retrying_unsafe_statuses() -> (
    None
):
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, headers={"x-request-id": "req-auth"})

    async with client(handler) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client).health_check()

    assert calls == 1
    assert result.status is ProviderHealthStatus.UNHEALTHY
    assert result.error_code is ProviderErrorCode.AUTHENTICATION_FAILED
    assert result.request_id == "req-auth"


@pytest.mark.asyncio
async def test_health_requires_the_exact_configured_model() -> None:
    async with client(
        lambda _: httpx.Response(
            200,
            headers={"x-request-id": "req-models"},
            json={"data": [{"id": "model-a-preview"}]},
        )
    ) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client).health_check()

    assert result.status is ProviderHealthStatus.UNHEALTHY
    assert result.error_code is ProviderErrorCode.MODEL_NOT_FOUND
    assert result.request_id == "req-models"


@pytest.mark.asyncio
async def test_health_discards_unsafe_request_id() -> None:
    async with client(
        lambda _: httpx.Response(
            200,
            headers={"x-request-id": "unsafe id"},
            json={"data": [{"id": "model-a"}]},
        )
    ) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client).health_check()

    assert result.status is ProviderHealthStatus.HEALTHY
    assert result.request_id is None


@pytest.mark.asyncio
async def test_health_marks_a_malformed_models_payload_as_invalid_response() -> None:
    async with client(
        lambda _: httpx.Response(
            200,
            headers={"x-request-id": "req-malformed"},
            json={"data": "not-a-list"},
        )
    ) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client).health_check()

    assert result.status is ProviderHealthStatus.UNHEALTHY
    assert result.error_code is ProviderErrorCode.INVALID_RESPONSE
    assert result.request_id == "req-malformed"


@pytest.mark.asyncio
async def test_health_transport_failure_is_bounded_and_non_throwing() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("sentinel-transport-message")

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with client(handler) as http_client:
        result = await ShineShopAdapter(settings(), client=http_client, sleep=sleep).health_check()

    assert result.status is ProviderHealthStatus.UNHEALTHY
    assert result.error_code is ProviderErrorCode.UNAVAILABLE
    assert result.request_id is None
    assert calls == 3
    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_logs_and_exceptions_do_not_leak_sensitive_remote_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    async with client(
        lambda _: httpx.Response(
            400,
            headers={"x-request-id": "bad id\nreq-safe"},
            content=SENTINEL_BODY.encode(),
        )
    ) as http_client:
        adapter = ShineShopAdapter(settings(), client=http_client)
        with pytest.raises(ProviderError) as raised:
            await adapter.generate(request(SENTINEL_INPUT))

    rendered = "\n".join(record.getMessage() for record in caplog.records) + str(raised.value)
    assert raised.value.request_id is None
    assert SENTINEL_KEY not in rendered
    assert SENTINEL_INPUT not in rendered
    assert SENTINEL_OUTPUT not in rendered
    assert SENTINEL_BODY not in rendered
