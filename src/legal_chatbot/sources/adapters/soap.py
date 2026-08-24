"""Fail-closed, read-only SOAP adapter for the residual VBQPPL lane.

The WSDL is treated as untrusted transport metadata: it can establish only the
two registry-approved read operations and one same-host SOAP 1.1 endpoint.
"""

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import httpx

from legal_chatbot.core.logging import get_logger
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import (
    DiscoveryCandidate,
    DiscoveryRequest,
    FetchApprovedDocumentRef,
    LegalDocumentSnapshot,
    ProvenanceType,
    SourceErrorCode,
    SourceHealth,
    SourceHealthStatus,
    SourceProvenance,
)
from legal_chatbot.sources.registry import SourceSystemConfig, VBQPPLReadManifest

_OPERATIONS: Final = ("GetListVanBanByListSKH", "GetVanBanById")
_SOAP11_WSDL: Final = "http://schemas.xmlsoap.org/wsdl/soap/"
_SOAP12_WSDL: Final = "http://schemas.xmlsoap.org/wsdl/soap12/"
_SOAP11_ENVELOPE: Final = "http://schemas.xmlsoap.org/soap/envelope/"
_VBQPPL_NAMESPACE: Final = "http://tempuri.org/"
_XSI_NAMESPACE: Final = "http://www.w3.org/2001/XMLSchema-instance"
_MAX_SOAP_ID: Final = 2_147_483_647
_SAFE_ACTION = re.compile(r"[^\x21-\x7e]")
_ACTIONS: Final = {
    "GetListVanBanByListSKH": "http://tempuri.org/GetListVanBanByListSKH",
    "GetVanBanById": "http://tempuri.org/GetVanBanById",
}


@dataclass(frozen=True)
class _SoapSchema:
    endpoint: str
    actions: dict[str, str]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str | None:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else None


def _safe_positive_id(value: str) -> int | None:
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        return None
    parsed = int(value)
    return parsed if parsed <= _MAX_SOAP_ID else None


def _safe_xml_root(payload: bytes) -> ET.Element | None:
    # ElementTree does not fetch external entities, but rejecting declarations
    # also prevents entity-expansion payloads before parsing them.
    if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
        return None
    try:
        return ET.fromstring(payload)
    except ET.ParseError:
        return None


def _soap_fault(root: ET.Element) -> bool:
    """Recognize a fault without retaining its remote code, text, or XML."""
    return any(_local_name(element.tag) == "Fault" for element in root.iter())


def _valid_https_url(value: str, *, expected_host: str | None = None) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme.lower() == "https"
            and parsed.hostname is not None
            and parsed.hostname.lower() == (expected_host or parsed.hostname).lower()
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and not parsed.query
        )
    except ValueError:
        return False


def _matches_canonical_origin(value: str | None, origin: str) -> bool:
    if not isinstance(value, str) or not _valid_https_url(origin):
        return False
    try:
        candidate, expected = urlsplit(value), urlsplit(origin)
        return (
            _valid_https_url(value)
            and candidate.scheme.lower() == expected.scheme.lower()
            and candidate.netloc.lower() == expected.netloc.lower()
            and bool(candidate.path)
        )
    except ValueError:
        return False


def _parse_wsdl(payload: bytes, *, base_host: str) -> _SoapSchema | None:
    root = _safe_xml_root(payload)
    if root is None:
        return None

    # An action must be identical wherever a SOAP binding declares it.  A
    # portType operation alone never authorizes a request.
    candidates: dict[str, set[str]] = {operation: set() for operation in _OPERATIONS}
    invalid_action = False
    for binding in root.iter():
        if _local_name(binding.tag) != "binding":
            continue
        for operation in binding:
            name = operation.attrib.get("name")
            if _local_name(operation.tag) != "operation" or name not in candidates:
                continue
            for child in operation:
                action = child.attrib.get("soapAction")
                is_soap_operation = _local_name(child.tag) == "operation" and _namespace(
                    child.tag
                ) in {_SOAP11_WSDL, _SOAP12_WSDL}
                if not is_soap_operation:
                    continue
                if action and len(action) <= 512 and not _SAFE_ACTION.search(action):
                    candidates[name].add(action)
                else:
                    invalid_action = True
    if invalid_action or any(
        candidates[operation] != {_ACTIONS[operation]} for operation in _OPERATIONS
    ):
        return None

    endpoints = {
        location
        for element in root.iter()
        if _local_name(element.tag) == "address"
        and _namespace(element.tag) == _SOAP11_WSDL
        and (location := element.attrib.get("location"))
        and _valid_https_url(location, expected_host=base_host)
    }
    if len(endpoints) != 1:
        return None
    return _SoapSchema(
        endpoint=next(iter(endpoints)),
        actions=dict(_ACTIONS),
    )


class VBQPPLSoapAdapter:
    """Use only the fixed, read-only VBQPPL SOAP operations.

    The source registry supplies source transport authority; the manifest supplies
    exact document authority. Injected source, manifest, and client values are test/DI
    seams; the validated manifest remains the document authorization boundary.
    """

    def __init__(
        self,
        settings: SourceSettings,
        source: SourceSystemConfig,
        client: httpx.AsyncClient | None = None,
        manifest: VBQPPLReadManifest | None = None,
    ) -> None:
        self._settings = settings
        self._source = source
        if manifest is None:
            from legal_chatbot.sources.registry import load_manifest

            manifest = load_manifest(settings.vbqppl_read_manifest_path)
        self._base_url, self._references, self._discovery_requests = self._validate_source(
            source, manifest
        )
        base_host = urlsplit(self._base_url).hostname
        if base_host is None:  # Defensive narrowing for static type checkers.
            raise SourceError(
                SourceErrorCode.SOURCE_NOT_CONFIGURED, source_id="VBQPPL", operation="init"
            )
        self._base_host = base_host
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=settings.soap_connect_timeout_seconds,
                read=settings.soap_response_timeout_seconds,
                write=settings.soap_response_timeout_seconds,
                pool=settings.soap_connect_timeout_seconds,
            ),
            verify=settings.soap_tls_verify,
            follow_redirects=False,
            trust_env=False,
        )
        self._logger = get_logger()
        self._schema: _SoapSchema | None = None

    @staticmethod
    def _validate_source(
        source: SourceSystemConfig, manifest: VBQPPLReadManifest
    ) -> tuple[str, tuple[FetchApprovedDocumentRef, ...], tuple[DiscoveryRequest, ...]]:
        base_url = getattr(source, "base_url", None)
        if (
            getattr(source, "id", None) != "VBQPPL"
            or getattr(source, "transport", None) != "SOAP"
            or getattr(source, "access_mode", None) != "READ_ONLY_ALLOWLIST"
            or getattr(source, "soap_operation_allowlist", None) != _OPERATIONS
            or not isinstance(base_url, str)
            or not _valid_https_url(base_url)
        ):
            raise SourceError(
                SourceErrorCode.SOURCE_NOT_CONFIGURED,
                source_id="VBQPPL",
                operation="init",
                retryable=False,
            )
        refs = manifest.fetch_refs("SOAP")
        requests = manifest.discovery_requests()
        canonical_origin = getattr(source, "canonical_page_origin", None)
        if (
            not isinstance(canonical_origin, str)
            or not all(
                ref.source_id == "VBQPPL"
                and ref.transport == "SOAP"
                and ref.operation == "GetVanBanById"
                and _matches_canonical_origin(ref.canonical_url, canonical_origin)
                for ref in refs
            )
            or not all(
                request.source_id == "VBQPPL" and request.transport == "SOAP"
                for request in requests
            )
        ):
            raise SourceError(
                SourceErrorCode.SOURCE_NOT_CONFIGURED, source_id="VBQPPL", operation="init"
            )
        return base_url, refs, requests

    @property
    def _wsdl_url(self) -> str:
        return f"{self._base_url}?WSDL"

    async def _read_response(self, response: httpx.Response) -> bytes | None:
        if response.is_stream_consumed:
            payload = response.content
            return payload if len(payload) <= self._settings.soap_max_response_bytes else None
        body = bytearray()
        async for chunk in response.aiter_raw():
            body.extend(chunk)
            if len(body) > self._settings.soap_max_response_bytes:
                return None
        return bytes(body)

    @staticmethod
    def _http_error(status_code: int, operation: str, *, document: bool = False) -> SourceError:
        if status_code in {401, 403}:
            code = SourceErrorCode.ACCESS_DENIED
        elif status_code == 404 and document:
            code = SourceErrorCode.DOCUMENT_NOT_FOUND
        elif status_code in {408, 504}:
            code = SourceErrorCode.TIMEOUT
        else:
            code = SourceErrorCode.UNAVAILABLE
        return SourceError(
            code,
            source_id="VBQPPL",
            operation=operation,
            retryable=code in {SourceErrorCode.TIMEOUT, SourceErrorCode.UNAVAILABLE},
            status_code=status_code,
        )

    @staticmethod
    def _failure(code: SourceErrorCode, operation: str) -> SourceError:
        return SourceError(code, source_id="VBQPPL", operation=operation)

    async def _get_wsdl(self) -> _SoapSchema:
        if self._schema is not None:
            return self._schema
        try:
            async with self._client.stream(
                "GET", self._wsdl_url, follow_redirects=False
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise self._http_error(response.status_code, "wsdl")
                payload = await self._read_response(response)
        except SourceError:
            raise
        except httpx.TimeoutException as exc:
            raise SourceError(
                SourceErrorCode.TIMEOUT,
                source_id="VBQPPL",
                operation="wsdl",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(
                SourceErrorCode.UNAVAILABLE,
                source_id="VBQPPL",
                operation="wsdl",
                retryable=True,
            ) from exc
        if payload is None:
            raise SourceError(
                SourceErrorCode.INVALID_RESPONSE,
                source_id="VBQPPL",
                operation="wsdl",
                status_code=200,
            )
        schema = _parse_wsdl(payload, base_host=self._base_host)
        if schema is None:
            raise SourceError(
                SourceErrorCode.INVALID_RESPONSE,
                source_id="VBQPPL",
                operation="wsdl",
                status_code=200,
            )
        self._schema = schema
        return schema

    async def _post_once(self, schema: _SoapSchema, operation: str, body: bytes) -> bytes:
        if operation not in _OPERATIONS:
            raise SourceError(SourceErrorCode.ACCESS_DENIED, source_id="VBQPPL", operation="post")
        try:
            async with self._client.stream(
                "POST",
                schema.endpoint,
                content=body,
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{schema.actions[operation]}"',
                },
                follow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise self._http_error(response.status_code, operation, document=True)
                payload = await self._read_response(response)
        except SourceError:
            raise
        except httpx.TimeoutException as exc:
            raise SourceError(
                SourceErrorCode.TIMEOUT,
                source_id="VBQPPL",
                operation=operation,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceError(
                SourceErrorCode.UNAVAILABLE,
                source_id="VBQPPL",
                operation=operation,
                retryable=True,
            ) from exc
        if payload is None:
            raise SourceError(
                SourceErrorCode.INVALID_RESPONSE,
                source_id="VBQPPL",
                operation=operation,
                status_code=200,
            )
        return payload

    @staticmethod
    def _discovery_body(document_number: str) -> bytes:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<soap:Envelope xmlns:soap="{_SOAP11_ENVELOPE}"><soap:Body>'
            f'<GetListVanBanByListSKH xmlns="{_VBQPPL_NAMESPACE}" xmlns:xsi="{_XSI_NAMESPACE}">'
            f"<skh>{xml_escape(document_number)}</skh>"
            '<ngaybanhanh xsi:nil="true"/><ngaycohieuluc xsi:nil="true"/>'
            "</GetListVanBanByListSKH></soap:Body></soap:Envelope>"
        ).encode()

    @staticmethod
    def _detail_body(soap_id: int) -> bytes:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<soap:Envelope xmlns:soap="{_SOAP11_ENVELOPE}"><soap:Body>'
            f'<GetVanBanById xmlns="{_VBQPPL_NAMESPACE}"><ItemID>{soap_id}</ItemID>'
            "</GetVanBanById></soap:Body></soap:Envelope>"
        ).encode()

    @staticmethod
    def _select_soap_id(payload: bytes, document_number: str) -> int:
        root = _safe_xml_root(payload)
        if root is None:
            raise VBQPPLSoapAdapter._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[0])
        if _soap_fault(root):
            raise VBQPPLSoapAdapter._failure(SourceErrorCode.UNAVAILABLE, "soap_fault")
        matches: list[ET.Element] = []
        for item in root.iter():
            if _local_name(item.tag) != "VanBanItem":
                continue
            direct_number = [
                (child.text or "").strip()
                for child in item
                if _local_name(child.tag) == "VBPQSokyhieu"
            ]
            if direct_number.count(document_number) == 1:
                matches.append(item)
        if not matches:
            raise VBQPPLSoapAdapter._failure(SourceErrorCode.DOCUMENT_NOT_FOUND, _OPERATIONS[0])
        if len(matches) != 1:
            raise VBQPPLSoapAdapter._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[0])
        direct_ids = [
            (child.text or "").strip() for child in matches[0] if _local_name(child.tag) == "ID"
        ]
        if len(direct_ids) != 1 or (soap_id := _safe_positive_id(direct_ids[0])) is None:
            raise VBQPPLSoapAdapter._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[0])
        return soap_id

    @staticmethod
    def _single_value(fields: dict[str, list[str]], *names: str) -> str | None:
        for name in names:
            values = [value for value in fields.get(name, []) if value]
            if len(values) == 1:
                return values[0]
            if len(values) > 1:
                return None
        return None

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    def _snapshot(
        self, payload: bytes, ref: FetchApprovedDocumentRef, soap_id: int
    ) -> LegalDocumentSnapshot:
        root = _safe_xml_root(payload)
        if root is None:
            raise self._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[1])
        if _soap_fault(root):
            raise self._failure(SourceErrorCode.UNAVAILABLE, "soap_fault")
        results = [
            element for element in root.iter() if _local_name(element.tag) == "GetVanBanByIdResult"
        ]
        if len(results) != 1:
            raise self._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[1])
        fields: dict[str, list[str]] = {}
        for child in results[0]:
            fields.setdefault(_local_name(child.tag), []).append((child.text or "").strip())
        direct_ids = fields.get("ID", [])
        if direct_ids.count(str(soap_id)) != 1:
            raise self._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[1])
        returned_numbers = [value for value in fields.get("VBPQSokyhieu", []) if value]
        if len(returned_numbers) > 1 or (
            returned_numbers and returned_numbers[0] != ref.document_number
        ):
            raise self._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[1])
        content = self._single_value(fields, "VBPQToanVan")
        metadata = self._single_value(fields, "Title", "VBPQTrichYeu", "VBPQSokyhieu")
        if content is None or metadata is None:
            raise self._failure(SourceErrorCode.INVALID_RESPONSE, _OPERATIONS[1])
        return LegalDocumentSnapshot(
            source_id="VBQPPL",
            external_id=ref.external_id,
            document_number=ref.document_number,
            title=self._single_value(fields, "Title", "VBPQTrichYeu"),
            document_type=self._single_value(fields, "LoaiVanBan", "VBPQLoaiVanBan"),
            issuing_authority=self._single_value(fields, "CoQuanBanHanh", "VBPQCoQuanBanHanh"),
            issue_date=self._parse_date(
                self._single_value(fields, "NgayBanHanh", "VBPQNgayBanHanh")
            ),
            effective_date=self._parse_date(
                self._single_value(fields, "NgayCoHieuLuc", "VBPQNgayCoHieuLuc")
            ),
            legal_status=self._single_value(fields, "TinhTrang", "VBPQTinhTrang"),
            canonical_url=ref.canonical_url,
            content_html=content,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            provenance=SourceProvenance(
                provenance_type=ProvenanceType.SOURCE_FETCH,
                source_id="VBQPPL",
                transport="SOAP",
                operation=_OPERATIONS[1],
                retrieved_at=datetime.now(UTC),
                canonical_url=ref.canonical_url,
                tls_verified=True,
            ),
        )

    async def list_documents(self) -> tuple[FetchApprovedDocumentRef, ...]:
        started_at = time.perf_counter()
        self._log("list_documents", started_at, "success", False, None)
        return self._references

    async def fetch_document(self, ref: FetchApprovedDocumentRef) -> LegalDocumentSnapshot:
        started_at = time.perf_counter()
        operation = "fetch_document"
        if not isinstance(ref, FetchApprovedDocumentRef) or ref not in self._references:
            error = SourceError(
                SourceErrorCode.DOCUMENT_NOT_ALLOWED,
                source_id="VBQPPL",
                operation=operation,
            )
            self._log(operation, started_at, "failure", error.retryable, None)
            raise error
        try:
            # An insecure configuration is diagnostic-only.  It must never send a
            # SOAP POST or manufacture official provenance.
            if not self._settings.soap_tls_verify:
                raise self._failure(SourceErrorCode.UNAVAILABLE, "tls")
            soap_id = _safe_positive_id(ref.external_id)
            if soap_id is None:
                raise self._failure(SourceErrorCode.DOCUMENT_NOT_ALLOWED, operation)
            schema = await self._get_wsdl()
            snapshot = self._snapshot(
                await self._post_once(schema, _OPERATIONS[1], self._detail_body(soap_id)),
                ref,
                soap_id,
            )
        except SourceError as error:
            self._log(operation, started_at, "failure", error.retryable, ref.external_id)
            raise
        self._log(operation, started_at, "success", False, ref.external_id)
        return snapshot

    async def discover_document(self, request: DiscoveryRequest) -> DiscoveryCandidate:
        """Perform exact SOAP discovery only for manifest-approved numbers."""
        started_at = time.perf_counter()
        operation = "discover_document"
        if not isinstance(request, DiscoveryRequest) or request not in self._discovery_requests:
            error = self._failure(SourceErrorCode.DOCUMENT_NOT_ALLOWED, operation)
            self._log(operation, started_at, "failure", error.retryable, None)
            raise error
        try:
            if not self._settings.soap_tls_verify:
                raise self._failure(SourceErrorCode.UNAVAILABLE, "tls")
            schema = await self._get_wsdl()
            external_id = self._select_soap_id(
                await self._post_once(
                    schema, _OPERATIONS[0], self._discovery_body(request.document_number)
                ),
                request.document_number,
            )
        except SourceError as error:
            self._log(operation, started_at, "failure", error.retryable, None)
            raise
        candidate = DiscoveryCandidate(
            source_id="VBQPPL",
            document_number=request.document_number,
            external_id=str(external_id),
            transport="SOAP",
        )
        self._log(operation, started_at, "success", False, None)
        return candidate

    async def health_check(self) -> SourceHealth:
        started_at = time.perf_counter()
        error_code: SourceErrorCode | None = None
        retryable = False
        try:
            await self._get_wsdl()
            if not self._settings.soap_tls_verify:
                error_code = SourceErrorCode.UNAVAILABLE
        except SourceError as exc:
            error_code = exc.code
            retryable = exc.retryable
        duration_ms = self._duration_ms(started_at)
        if error_code is not None:
            self._log("health_check", started_at, "unhealthy", retryable, None)
        else:
            self._log("health_check", started_at, "success", False, None)
        return SourceHealth(
            status=(
                SourceHealthStatus.HEALTHY if error_code is None else SourceHealthStatus.UNHEALTHY
            ),
            source_id="VBQPPL",
            transport="SOAP",
            duration_ms=duration_ms,
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
        retryable: bool,
        document_id: str | None,
    ) -> None:
        self._logger.info(
            "source_operation",
            extra={
                "source": "VBQPPL",
                "transport": "SOAP",
                "source_operation": operation,
                "source_document_id": document_id,
                "provenance_type": ProvenanceType.SOURCE_FETCH.value,
                "duration_ms": self._duration_ms(started_at),
                "outcome": outcome,
                "retry_count": 0,
                "retryable": retryable,
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
