"""Fail-closed REST fallback adapter using only manifest-approved exact fetch refs."""

import asyncio
import hashlib
import json
import math
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx

from legal_chatbot.core.logging import get_logger
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import (
    FetchApprovedDocumentRef,
    LegalDocumentSnapshot,
    ProvenanceType,
    SourceErrorCode,
    SourceHealth,
    SourceHealthStatus,
    SourceProvenance,
)
from legal_chatbot.sources.registry import SourceSystemConfig, VBQPPLReadManifest

_SOURCE_ID = "VBQPPL"
_TRANSPORT = "REST_FRONTEND_BACKING_API"
_FALLBACK_BASE_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api"
_FALLBACK_ACCESS_MODE = "READ_ONLY_EXACT_PATH_ALLOWLIST"
_CANONICAL_ORIGIN = "https://vbpl.vn"
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_MODEL_HTML_MAX_CHARS = 2_097_152
_ISO_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)


def _matches_canonical_origin(value: str | None, origin: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        candidate, expected = urlsplit(value), urlsplit(origin)
        return (
            candidate.scheme == expected.scheme == "https"
            and candidate.netloc == expected.netloc
            and bool(candidate.path)
            and candidate.query == candidate.fragment == ""
        )
    except ValueError:
        return False


class _CanonicalLinkParser(HTMLParser):
    """Collect only canonical-link hrefs without interpreting page content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        attributes = {name.lower(): value for name, value in attrs}
        rel = attributes.get("rel")
        href = attributes.get("href")
        if isinstance(rel, str) and isinstance(href, str) and "canonical" in rel.lower().split():
            self.hrefs.append(href)


@dataclass(frozen=True)
class _HttpResult:
    status_code: int
    body: bytes
    retry_count: int


class VBQPPLRestAdapter:
    """Read only manifest-approved VBQPPL REST documents and verify each provenance.

    Injected source, manifest, and client values are test/DI seams; the validated
    manifest remains the document authorization boundary.
    """

    def __init__(
        self,
        settings: SourceSettings,
        source: SourceSystemConfig,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        manifest: VBQPPLReadManifest | None = None,
    ) -> None:
        self._settings = settings
        self._source = source
        if manifest is None:
            from legal_chatbot.sources.registry import load_manifest

            manifest = load_manifest(settings.vbqppl_read_manifest_path)
        self._references = self._validate_source(source, manifest)
        self._client = client or self._build_client(settings)
        self._owns_client = client is None
        self._sleep = sleep
        self._logger = get_logger()

    @staticmethod
    def _build_client(settings: SourceSettings) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            base_url=f"{_FALLBACK_BASE_URL}/",
            timeout=httpx.Timeout(
                connect=settings.rest_connect_timeout_seconds,
                read=settings.rest_response_timeout_seconds,
                write=settings.rest_response_timeout_seconds,
                pool=settings.rest_connect_timeout_seconds,
            ),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            trust_env=False,
            follow_redirects=False,
            headers={},
        )
        # Do not inherit HTTPX's convenience User-Agent/Accept defaults.  Each
        # request below supplies the complete permitted application headers.
        client.headers = httpx.Headers()
        return client

    @staticmethod
    def _validate_source(
        source: SourceSystemConfig, manifest: VBQPPLReadManifest
    ) -> tuple[FetchApprovedDocumentRef, ...]:
        refs = manifest.fetch_refs(_TRANSPORT)
        valid = (
            source.id == _SOURCE_ID
            and source.fallback_transport == _TRANSPORT
            and source.fallback_base_url == _FALLBACK_BASE_URL
            and source.fallback_access_mode == _FALLBACK_ACCESS_MODE
            and source.canonical_page_origin == _CANONICAL_ORIGIN
            and all(
                ref.source_id == _SOURCE_ID
                and ref.transport == _TRANSPORT
                and ref.operation == f"GET {ref.detail_path}"
                and _matches_canonical_origin(ref.canonical_url, _CANONICAL_ORIGIN)
                for ref in refs
            )
        )
        if not valid:
            raise SourceError(
                SourceErrorCode.SOURCE_NOT_CONFIGURED,
                source_id=_SOURCE_ID,
                operation="configure_rest_fallback",
                status_code=503,
            )
        return refs

    async def aclose(self) -> None:
        """Close only a client created by this adapter."""
        if self._owns_client:
            await self._client.aclose()

    async def list_documents(self) -> tuple[FetchApprovedDocumentRef, ...]:
        """Return all exact REST fetch references without opening a connection."""
        started_at = time.perf_counter()
        self._log("list_documents", started_at, "success", 0, False, None)
        return self._references

    async def fetch_document(self, ref: FetchApprovedDocumentRef) -> LegalDocumentSnapshot:
        """Fetch the allowed gateway document and verify its canonical public page."""
        started_at = time.perf_counter()
        operation = "fetch_document"
        if not self._is_allowed_reference(ref):
            error = SourceError(
                SourceErrorCode.DOCUMENT_NOT_ALLOWED,
                source_id=_SOURCE_ID,
                operation=operation,
                status_code=400,
            )
            self._log(operation, started_at, "failure", 0, error.retryable, None)
            raise error

        retry_count = 0
        try:
            gateway = await self._get(
                f"{_FALLBACK_BASE_URL}{ref.detail_path}", {"Accept": "application/json"}
            )
            retry_count += gateway.retry_count
            data = self._parse_gateway(gateway, ref)
            canonical = await self._get(
                ref.canonical_url or "",
                {
                    "Accept": "text/html",
                    "User-Agent": "legal-chatbot-ueb-demo-m03/1.0",
                },
            )
            retry_count += canonical.retry_count
            self._validate_canonical(canonical, ref)
            snapshot = self._snapshot(data, ref)
        except SourceError as error:
            self._log(
                operation, started_at, "failure", retry_count, error.retryable, ref.external_id
            )
            raise

        self._log(operation, started_at, "success", retry_count, False, ref.external_id)
        return snapshot

    async def health_check(self) -> SourceHealth:
        """Probe the exact allowlisted gateway document without fetching its page."""
        started_at = time.perf_counter()
        retry_count = 0
        if not self._references:
            self._log("health_check", started_at, "unhealthy", 0, False, None)
            return SourceHealth(
                status=SourceHealthStatus.UNHEALTHY,
                source_id=_SOURCE_ID,
                transport=_TRANSPORT,
                duration_ms=self._duration_ms(started_at),
                error_code=SourceErrorCode.DOCUMENT_NOT_ALLOWED,
            )
        ref = self._references[0]
        try:
            result = await self._get(
                f"{_FALLBACK_BASE_URL}{ref.detail_path}", {"Accept": "application/json"}
            )
            retry_count = result.retry_count
            self._parse_gateway(result, ref)
        except SourceError as error:
            self._log(
                "health_check",
                started_at,
                "unhealthy",
                retry_count,
                error.retryable,
                ref.external_id,
            )
            return SourceHealth(
                status=SourceHealthStatus.UNHEALTHY,
                source_id=_SOURCE_ID,
                transport=_TRANSPORT,
                duration_ms=self._duration_ms(started_at),
                error_code=error.code,
            )

        self._log("health_check", started_at, "success", retry_count, False, ref.external_id)
        return SourceHealth(
            status=SourceHealthStatus.HEALTHY,
            source_id=_SOURCE_ID,
            transport=_TRANSPORT,
            duration_ms=self._duration_ms(started_at),
        )

    def _is_allowed_reference(self, ref: object) -> bool:
        return isinstance(ref, FetchApprovedDocumentRef) and ref in self._references

    async def _get(self, url: str, headers: Mapping[str, str]) -> _HttpResult:
        """Perform a bounded GET with retries limited to safe, known failures."""
        retry_count = 0
        for attempt in range(self._settings.rest_max_attempts):
            retry_after: float | None = None
            try:
                request = httpx.Request("GET", url, headers=headers)
                response = await self._client.send(request, stream=True, follow_redirects=False)
                try:
                    body = await self._read_bounded(response)
                    if response.status_code == 200:
                        return _HttpResult(response.status_code, body, retry_count)
                    error = self._status_error(response.status_code)
                    retry_after = self._retry_after(response)
                    retryable_get = response.status_code in _RETRY_STATUSES
                finally:
                    await response.aclose()
            except httpx.TimeoutException:
                error = SourceError(
                    SourceErrorCode.TIMEOUT,
                    source_id=_SOURCE_ID,
                    operation="get",
                    retryable=True,
                )
                retryable_get = True
            except httpx.TransportError:
                error = SourceError(
                    SourceErrorCode.UNAVAILABLE,
                    source_id=_SOURCE_ID,
                    operation="get",
                    retryable=True,
                )
                retryable_get = True

            if not retryable_get or attempt == self._settings.rest_max_attempts - 1:
                raise error
            retry_count += 1
            await self._sleep(self._retry_delay(retry_count, retry_after))

        raise SourceError(SourceErrorCode.UNAVAILABLE, source_id=_SOURCE_ID, operation="get")

    async def _read_bounded(self, response: httpx.Response) -> bytes:
        content = bytearray()
        try:
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self._settings.rest_max_response_bytes:
                    raise SourceError(
                        SourceErrorCode.INVALID_RESPONSE,
                        source_id=_SOURCE_ID,
                        operation="get",
                        status_code=response.status_code,
                    )
            return bytes(content)
        finally:
            content.clear()

    def _parse_gateway(
        self, result: _HttpResult, ref: FetchApprovedDocumentRef
    ) -> dict[str, object]:
        if result.status_code != 200:
            raise self._status_error(result.status_code)
        try:
            payload = json.loads(result.body)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
            raise self._invalid_response(result.status_code) from None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or payload.get("statusCode") != 200
            or not isinstance(payload.get("data"), dict)
        ):
            raise self._invalid_response(result.status_code)
        data = payload["data"]
        if not self._matches_id(data.get("id"), ref) or data.get("docNum") != ref.document_number:
            raise SourceError(
                SourceErrorCode.PROVENANCE_MISMATCH,
                source_id=_SOURCE_ID,
                operation="parse_gateway",
                status_code=result.status_code,
            )
        content_container = data.get("documentContent")
        content = content_container.get("content") if isinstance(content_container, dict) else None
        if not self._is_full_html(content):
            raise self._invalid_response(result.status_code)
        return data

    def _validate_canonical(self, result: _HttpResult, ref: FetchApprovedDocumentRef) -> None:
        if result.status_code != 200:
            raise self._status_error(result.status_code)
        try:
            parser = _CanonicalLinkParser()
            parser.feed(result.body.decode("utf-8"))
            parser.close()
        except (UnicodeDecodeError, ValueError):
            raise self._invalid_response(result.status_code) from None
        if parser.hrefs != [ref.canonical_url]:
            raise SourceError(
                SourceErrorCode.PROVENANCE_MISMATCH,
                source_id=_SOURCE_ID,
                operation="verify_canonical",
                status_code=result.status_code,
            )

    def _snapshot(
        self, data: dict[str, object], ref: FetchApprovedDocumentRef
    ) -> LegalDocumentSnapshot:
        content_container = data["documentContent"]
        content = content_container["content"] if isinstance(content_container, dict) else ""
        if not isinstance(content, str):
            raise self._invalid_response(200)
        if len(content) > _MODEL_HTML_MAX_CHARS:
            raise self._invalid_response(200)
        return LegalDocumentSnapshot(
            source_id=_SOURCE_ID,
            external_id=ref.external_id,
            document_number=ref.document_number,
            title=self._optional_text(data.get("title"), 4_096),
            document_type=self._nested_text(data.get("docType"), "name", 512),
            issuing_authority=self._issuing_authority(data),
            issue_date=self._optional_datetime(data.get("issueDate")),
            effective_date=self._optional_datetime(data.get("effFrom")),
            source_updated_at=self._optional_datetime(data.get("updatedDate")),
            legal_status=self._legal_status(data.get("effStatus")),
            canonical_url=ref.canonical_url,
            content_html=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            provenance=SourceProvenance(
                provenance_type=ProvenanceType.SOURCE_FETCH,
                source_id=_SOURCE_ID,
                transport=_TRANSPORT,
                operation=f"GET {ref.detail_path} + canonical verification",
                retrieved_at=datetime.now(UTC),
                canonical_url=ref.canonical_url,
                tls_verified=True,
            ),
        )

    def _status_error(self, status_code: int) -> SourceError:
        if status_code in (401, 403):
            code, retryable = SourceErrorCode.ACCESS_DENIED, False
        elif status_code == 404:
            code, retryable = SourceErrorCode.DOCUMENT_NOT_FOUND, False
        elif status_code == 408:
            code, retryable = SourceErrorCode.TIMEOUT, True
        elif status_code >= 500 or status_code == 429:
            code, retryable = SourceErrorCode.UNAVAILABLE, True
        else:
            code, retryable = SourceErrorCode.INVALID_RESPONSE, False
        return SourceError(
            code,
            source_id=_SOURCE_ID,
            operation="get",
            retryable=retryable,
            status_code=status_code,
        )

    def _invalid_response(self, status_code: int) -> SourceError:
        return SourceError(
            SourceErrorCode.INVALID_RESPONSE,
            source_id=_SOURCE_ID,
            operation="parse_gateway",
            status_code=status_code,
        )

    @staticmethod
    def _matches_id(value: object, ref: FetchApprovedDocumentRef) -> bool:
        return value == ref.external_id or (
            isinstance(value, int)
            and not isinstance(value, bool)
            and ref.external_id.isdecimal()
            and value == int(ref.external_id)
        )

    def _is_full_html(self, value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        try:
            encoded = value.encode("utf-8")
        except UnicodeError:
            return False
        return (
            len(encoded) <= self._settings.rest_max_response_bytes
            and len(value) <= _MODEL_HTML_MAX_CHARS
            and "<" in value
            and ">" in value
        )

    @staticmethod
    def _optional_text(value: object, max_length: int) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized or len(normalized) > max_length:
            return None
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized):
            return None
        return normalized

    @classmethod
    def _nested_text(cls, value: object, key: str, max_length: int) -> str | None:
        return cls._optional_text(value.get(key), max_length) if isinstance(value, dict) else None

    @classmethod
    def _issuing_authority(cls, data: dict[str, object]) -> str | None:
        organization = cls._nested_text(data.get("organization"), "name", 1_024)
        return organization or cls._optional_text(data.get("agencyName"), 1_024)

    @classmethod
    def _legal_status(cls, value: object) -> str | None:
        if isinstance(value, dict):
            return cls._optional_text(value.get("name"), 256)
        return cls._optional_text(value, 256)

    @staticmethod
    def _optional_datetime(value: object) -> datetime | None:
        if not isinstance(value, str) or not _ISO_DATETIME.fullmatch(value):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _retry_after(self, response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError, IndexError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                return None
            seconds = (retry_at - datetime.now(UTC)).total_seconds()
            if seconds < 0:
                seconds = 0.0
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return min(seconds, self._settings.rest_retry_max_seconds)

    def _retry_delay(self, retry_count: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        return min(0.25 * 2 ** (retry_count - 1), self._settings.rest_retry_max_seconds)

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return max(0.0, (time.perf_counter() - started_at) * 1000)

    def _log(
        self,
        operation: str,
        started_at: float,
        outcome: str,
        retry_count: int,
        retryable: bool,
        document_id: str | None,
    ) -> None:
        self._logger.info(
            "source_operation",
            extra={
                "source": _SOURCE_ID,
                "transport": _TRANSPORT,
                "source_operation": operation,
                "source_document_id": document_id,
                "provenance_type": ProvenanceType.SOURCE_FETCH.value,
                "duration_ms": self._duration_ms(started_at),
                "outcome": outcome,
                "retry_count": retry_count,
                "retryable": retryable,
            },
        )
