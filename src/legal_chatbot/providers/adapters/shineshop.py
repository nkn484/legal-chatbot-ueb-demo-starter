"""Bounded async adapter for the SHINE SHOP Responses API."""

import asyncio
import json
import math
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from legal_chatbot.core.logging import get_logger
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

_HEALTH_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_UNAVAILABLE_STATUSES = frozenset({500, 502, 503, 504})
_REQUEST_REJECTED_STATUSES = frozenset({400, 404, 413})


class ShineShopAdapter:
    """Translate provider-neutral models into bounded SHINE SHOP HTTP requests."""

    def __init__(
        self,
        settings: ProviderSettings,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._client = client or self._build_client(settings)
        self._owns_client = client is None
        self._sleep = sleep
        self._logger = get_logger()

    @staticmethod
    def _build_client(settings: ProviderSettings) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{settings.base_url.rstrip('/')}/",
            headers={
                "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.response_timeout_seconds,
                write=settings.response_timeout_seconds,
                pool=settings.connect_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            trust_env=False,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        """Close only the HTTP client created by this adapter."""
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate exactly one non-streaming response without retries."""
        self._validate_generation(request)
        started_at = time.perf_counter()
        request_id: str | None = None
        try:
            async with self._client.stream(
                "POST",
                "responses",
                json={
                    "model": self._settings.model,
                    "input": request.input_text,
                    "max_output_tokens": request.max_output_tokens,
                    "stream": False,
                },
            ) as response:
                request_id = self._safe_request_id(response)
                if response.status_code != 200:
                    model_not_found = (
                        response.status_code == 404
                        and await self._has_stable_model_not_found_code(response)
                    )
                    raise self._status_error(response, request_id, model_not_found)
                text = self._extract_output_text(
                    await self._read_json_bounded(response, request_id),
                    request_id,
                    response.status_code,
                )
        except ProviderError as error:
            self._log("generate", started_at, "failure", request_id, 0, error.retryable)
            raise
        except httpx.TimeoutException:
            error = ProviderError(ProviderErrorCode.TIMEOUT, retryable=True, request_id=request_id)
            self._log("generate", started_at, "failure", request_id, 0, error.retryable)
            raise error from None
        except httpx.TransportError:
            error = ProviderError(
                ProviderErrorCode.UNAVAILABLE, retryable=True, request_id=request_id
            )
            self._log("generate", started_at, "failure", request_id, 0, error.retryable)
            raise error from None

        duration_ms = self._duration_ms(started_at)
        result = GenerationResult(
            text=text,
            provider=self._settings.provider,
            model=self._settings.model,
            request_id=request_id,
            duration_ms=duration_ms,
        )
        self._log("generate", started_at, "success", request_id, 0, False)
        return result

    async def health_check(self) -> ProviderHealth:
        """Return exact-model health and never expose remote failures to callers."""
        started_at = time.perf_counter()
        request_id: str | None = None
        retry_count = 0

        for attempt in range(self._settings.health_max_attempts):
            retry_after: float | None = None
            retryable_get = False
            try:
                async with self._client.stream("GET", "models") as response:
                    request_id = self._safe_request_id(response)
                    if response.status_code == 200:
                        try:
                            payload = await self._read_json_bounded(response, request_id)
                        except ProviderError as error:
                            return self._unhealthy(
                                error.code, request_id, started_at, retry_count, error.retryable
                            )
                        if not self._is_models_payload(payload):
                            return self._unhealthy(
                                ProviderErrorCode.INVALID_RESPONSE,
                                request_id,
                                started_at,
                                retry_count,
                                False,
                            )
                        if self._contains_exact_model(payload):
                            return self._healthy(request_id, started_at, retry_count)
                        return self._unhealthy(
                            ProviderErrorCode.MODEL_NOT_FOUND,
                            request_id,
                            started_at,
                            retry_count,
                            False,
                        )

                    model_not_found = (
                        response.status_code == 404
                        and await self._has_stable_model_not_found_code(response)
                    )
                    error = self._status_error(response, request_id, model_not_found)
                    retry_after = self._retry_after(response)
                    retryable_get = response.status_code in _HEALTH_RETRY_STATUSES
            except httpx.TimeoutException:
                error = ProviderError(
                    ProviderErrorCode.TIMEOUT, retryable=True, request_id=request_id
                )
                retryable_get = True
            except httpx.TransportError:
                error = ProviderError(
                    ProviderErrorCode.UNAVAILABLE, retryable=True, request_id=request_id
                )
                retryable_get = True

            if not retryable_get or attempt == self._settings.health_max_attempts - 1:
                return self._unhealthy(
                    error.code, request_id, started_at, retry_count, error.retryable
                )
            retry_count += 1
            await self._sleep(self._retry_delay(retry_count, retry_after))

        return self._unhealthy(
            ProviderErrorCode.UNAVAILABLE, request_id, started_at, retry_count, False
        )

    def _validate_generation(self, request: GenerationRequest) -> None:
        if len(request.input_text) > self._settings.max_input_chars:
            raise ProviderError(ProviderErrorCode.REQUEST_REJECTED, retryable=False)
        if request.max_output_tokens > self._settings.max_output_tokens:
            raise ProviderError(ProviderErrorCode.REQUEST_REJECTED, retryable=False)

    async def _read_json_bounded(self, response: httpx.Response, request_id: str | None) -> object:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > self._settings.max_response_bytes:
                content.clear()
                raise ProviderError(
                    ProviderErrorCode.INVALID_RESPONSE,
                    retryable=False,
                    status_code=response.status_code,
                    request_id=request_id,
                )
        try:
            return json.loads(bytes(content))
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                retryable=False,
                status_code=response.status_code,
                request_id=request_id,
            ) from None
        finally:
            content.clear()

    async def _has_stable_model_not_found_code(self, response: httpx.Response) -> bool:
        try:
            payload = await self._read_json_bounded(response, self._safe_request_id(response))
        except ProviderError:
            return False
        if not isinstance(payload, dict):
            return False
        error = payload.get("error")
        code = error.get("code") if isinstance(error, dict) else payload.get("code")
        return code == ProviderErrorCode.MODEL_NOT_FOUND.value

    def _extract_output_text(
        self, payload: object, request_id: str | None, status_code: int
    ) -> str:
        if not isinstance(payload, dict) or not isinstance(payload.get("output"), list):
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                status_code=status_code,
                request_id=request_id,
            )
        parts: list[str] = []
        for item in payload["output"]:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        text = "".join(parts).strip()
        if not text or len(text.encode("utf-8")) > self._settings.max_response_bytes:
            raise ProviderError(
                ProviderErrorCode.INVALID_RESPONSE,
                status_code=status_code,
                request_id=request_id,
            )
        return text

    def _status_error(
        self, response: httpx.Response, request_id: str | None, model_not_found: bool
    ) -> ProviderError:
        status_code = response.status_code
        if status_code in (401, 403):
            return ProviderError(
                ProviderErrorCode.AUTHENTICATION_FAILED,
                retryable=False,
                status_code=status_code,
                request_id=request_id,
            )
        if status_code == 429:
            return ProviderError(
                ProviderErrorCode.RATE_LIMITED,
                retryable=True,
                status_code=status_code,
                request_id=request_id,
                retry_after_seconds=self._retry_after(response),
            )
        if status_code == 404 and model_not_found:
            return ProviderError(
                ProviderErrorCode.MODEL_NOT_FOUND,
                retryable=False,
                status_code=status_code,
                request_id=request_id,
            )
        if status_code in _REQUEST_REJECTED_STATUSES:
            return ProviderError(
                ProviderErrorCode.REQUEST_REJECTED,
                retryable=False,
                status_code=status_code,
                request_id=request_id,
            )
        if status_code == 408:
            return ProviderError(
                ProviderErrorCode.TIMEOUT,
                retryable=True,
                status_code=status_code,
                request_id=request_id,
            )
        return ProviderError(
            ProviderErrorCode.UNAVAILABLE,
            retryable=True,
            status_code=status_code,
            request_id=request_id,
        )

    def _retry_after(self, response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            if retry_at.tzinfo is None:
                return None
            seconds = (retry_at - datetime.now(UTC)).total_seconds()
            if seconds < 0:
                return 0.0
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return min(seconds, self._settings.retry_after_max_seconds)

    def _retry_delay(self, retry_count: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        return min(0.25 * 2 ** (retry_count - 1), self._settings.retry_after_max_seconds)

    def _contains_exact_model(self, payload: object) -> bool:
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            return False
        return any(
            isinstance(item, dict) and item.get("id") == self._settings.model
            for item in payload["data"]
        )

    @staticmethod
    def _is_models_payload(payload: object) -> bool:
        return isinstance(payload, dict) and isinstance(payload.get("data"), list)

    @staticmethod
    def _safe_request_id(response: httpx.Response) -> str | None:
        return sanitize_request_id(response.headers.get("x-request-id"))

    def _healthy(
        self, request_id: str | None, started_at: float, retry_count: int
    ) -> ProviderHealth:
        self._log("health_check", started_at, "success", request_id, retry_count, False)
        return ProviderHealth(
            status=ProviderHealthStatus.HEALTHY,
            provider=self._settings.provider,
            model=self._settings.model,
            request_id=request_id,
            duration_ms=self._duration_ms(started_at),
        )

    def _unhealthy(
        self,
        error_code: ProviderErrorCode,
        request_id: str | None,
        started_at: float,
        retry_count: int,
        retryable: bool,
    ) -> ProviderHealth:
        self._log("health_check", started_at, "unhealthy", request_id, retry_count, retryable)
        return ProviderHealth(
            status=ProviderHealthStatus.UNHEALTHY,
            provider=self._settings.provider,
            model=self._settings.model,
            request_id=request_id,
            duration_ms=self._duration_ms(started_at),
            error_code=error_code,
        )

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return max(0.0, (time.perf_counter() - started_at) * 1000)

    def _log(
        self,
        operation: str,
        started_at: float,
        outcome: str,
        request_id: str | None,
        retry_count: int,
        retryable: bool,
    ) -> None:
        self._logger.info(
            "provider_operation",
            extra={
                "provider": self._settings.provider,
                "model": self._settings.model,
                "operation": operation,
                "duration_ms": self._duration_ms(started_at),
                "outcome": outcome,
                "provider_request_id": request_id,
                "retry_count": retry_count,
                "retryable": retryable,
            },
        )
