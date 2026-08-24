"""Small, fail-closed M00 probes for external demo dependencies.

This module deliberately contains no application integration code.  It is a
standalone operator tool: all remote data is treated as untrusted and output
is restricted to normalized, redacted probe results.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

import httpx

from env_loader import load_repo_env


SHINE_BASE_URL = "https://api.shineshop.dev/v1"
ALLOWED_OUTCOMES = frozenset({"PASS", "BLOCKED_EXTERNAL", "NOT_MEASURED"})
VBQPPL_ALLOWLIST = frozenset({"GetListVanBanByListSKH", "GetVanBanById"})
VBQPPL_OFFICIAL_HOST = "ws.vbpl.vn"
SOAP_BINDING_NAMESPACES = frozenset({"http://schemas.xmlsoap.org/wsdl/soap/", "http://schemas.xmlsoap.org/wsdl/soap12/"})
SOAP11_BINDING_NAMESPACE = "http://schemas.xmlsoap.org/wsdl/soap/"
SOAP11_ENVELOPE_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
VBQPPL_NAMESPACE = "http://tempuri.org/"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
MAX_RESPONSE_BYTES = 256 * 1024
MAX_REST_RESPONSE_BYTES = 1024 * 1024
MAX_VBQPPL_DOCUMENT_NUMBER_CHARS = 64
MAX_VBQPPL_ITEM_SCAN = 64
MAX_RETRY_AFTER_SECONDS = 2.0
MAX_MODEL_IDS_IN_DETAILS = 100
MAX_MODEL_ID_CHARS = 128
MAX_ERROR_FIELD_CHARS = 128
TIMEOUT = httpx.Timeout(60.0, connect=10.0)
REST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
VBQPPL_DOCUMENT_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/.-]{0,63}$")
VBQPPL_REST_TRANSPORT = "REST_FRONTEND_BACKING_API"
VBQPPL_REST_BASE_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api"
VBQPPL_REST_DOCUMENT_ID = 175258
VBQPPL_REST_DOCUMENT_NUMBER = "63/2025/QH15"
VBQPPL_REST_GATEWAY_URL = f"{VBQPPL_REST_BASE_URL}/qtdc/public/doc/{VBQPPL_REST_DOCUMENT_ID}"
VBQPPL_CANONICAL_PAGE_URL = "https://vbpl.vn/van-ban/chi-tiet/luat-to-chuc-chinh-phu-so-63-2025-qh15--175258"
VBQPPL_CANONICAL_PAGE_HEADERS = MappingProxyType({"User-Agent": "legal-chatbot-ueb-demo-m00/1.0", "Accept": "text/html,application/xhtml+xml"})


@dataclass(frozen=True)
class ProbeResult:
    probe: str
    outcome: str
    status: int | None = None
    duration_ms: int | None = None
    details: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    x_request_id: str | None = None

    def to_json(self) -> str:
        if self.outcome not in ALLOWED_OUTCOMES:
            raise ValueError("invalid normalized outcome")
        return json.dumps(redact_secrets(asdict(self)), sort_keys=True, separators=(",", ":"))


def redact_secrets(value: Any) -> Any:
    """Remove values associated with credential-like keys at every nesting level."""
    sensitive_parts = ("authorization", "api_key", "apikey", "secret", "token", "password", "cookie", "header")
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            name = str(key)
            if any(part in name.lower() for part in sensitive_parts):
                clean[name] = "[REDACTED]"
            else:
                clean[name] = redact_secrets(child)
        return clean
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    return value


def _error(kind: str, code: str) -> dict[str, str]:
    return {"type": kind, "code": code}


def _duration_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def _read_limited(response: httpx.Response, limit: int = MAX_RESPONSE_BYTES) -> bytes | None:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        return min(MAX_RETRY_AFTER_SECONDS, max(0.0, float(raw)))
    except ValueError:
        try:
            return min(MAX_RETRY_AFTER_SECONDS, max(0.0, parsedate_to_datetime(raw).timestamp() - time.time()))
        except (TypeError, ValueError, IndexError, OverflowError):
            return 0.0


def _get_once_or_retry(
    client: httpx.Client,
    url: str,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int | None, bytes | None, dict[str, str], dict[str, str] | None]:
    """GET with at most two total attempts, only for explicitly safe failures."""
    last_error: dict[str, str] | None = None
    for attempt in range(2):
        try:
            with client.stream("GET", url) as response:
                status = response.status_code
                body = _read_limited(response)
                if body is None:
                    return status, None, {}, _error("response", "response_too_large")
                if status in {429, 502, 503, 504} and attempt == 0:
                    sleep(_retry_after(response))
                    continue
                return status, body, dict(response.headers), None
        except httpx.TransportError:
            last_error = _error("transport", "transport_error")
            if attempt == 0:
                continue
    return None, None, {}, last_error or _error("transport", "transport_error")


def _safe_request_id(headers: Mapping[str, str]) -> str | None:
    value = headers.get("x-request-id") or headers.get("X-Request-Id")
    if not value:
        return None
    # Request IDs are diagnostic strings, not arbitrary response payloads.
    return value[:128] if all(32 <= ord(ch) < 127 for ch in value[:128]) else None


def _safe_bounded_text(value: Any, limit: int = MAX_ERROR_FIELD_CHARS) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    return value if all(32 <= ord(char) < 127 for char in value) else None


def _discovered_model_ids(payload: Any) -> tuple[list[str], list[str]] | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    raw_ids = [item["id"] for item in payload["data"] if isinstance(item, dict) and isinstance(item.get("id"), str)]
    safe_ids = [model_id for model_id in raw_ids if _safe_bounded_text(model_id, MAX_MODEL_ID_CHARS) is not None]
    return raw_ids, safe_ids[:MAX_MODEL_IDS_IN_DETAILS]


def _shine_error_from_body(body: bytes) -> dict[str, str]:
    """Extract only documented error.type and error.code, never error messages."""
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return _error("http", "http_status")
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return _error("http", "http_status")
    error_type = _safe_bounded_text(error.get("type"))
    error_code = _safe_bounded_text(error.get("code"))
    if error_type and error_code:
        return _error(error_type, error_code)
    return _error("http", "http_status")


def _retry_details(response: httpx.Response) -> dict[str, Any]:
    return {
        "retryable": response.status_code in {408, 429, 500, 502, 503, 504},
        "retry_after_seconds": _retry_after(response),
    }


def probe_shine_models(
    api_key: str | None,
    expected_model: str | None = None,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ProbeResult:
    start = time.monotonic()
    if not api_key:
        return ProbeResult("shine.models", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), error=_error("config", "missing_api_key"))
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"Authorization": f"Bearer {api_key}"}, trust_env=False)
    try:
        status, body, _headers, error = _get_once_or_retry(client, f"{SHINE_BASE_URL}/models", sleep=sleep)
        if error:
            return ProbeResult("shine.models", "BLOCKED_EXTERNAL", status, _duration_ms(start), error=error)
        if status != 200 or body is None:
            return ProbeResult("shine.models", "BLOCKED_EXTERNAL", status, _duration_ms(start), error=_error("http", "http_status"))
        try:
            discovered = _discovered_model_ids(json.loads(body))
        except ValueError:
            discovered = None
        if discovered is None:
            return ProbeResult("shine.models", "BLOCKED_EXTERNAL", status, _duration_ms(start), error=_error("response", "invalid_json"))
        model_ids, safe_model_ids = discovered
        found = expected_model is None or expected_model in model_ids  # Exact, case-sensitive membership when requested.
        return ProbeResult(
            "shine.models",
            "PASS" if found else "BLOCKED_EXTERNAL",
            status,
            _duration_ms(start),
            details={"model_ids": safe_model_ids, "model_count": len(model_ids), "exact_match": found},
            error=None if found else _error("validation", "model_not_discovered"),
        )
    finally:
        if own_client:
            client.close()


def _output_summary(payload: Any) -> dict[str, int]:
    """Report only shape and character counts, never model output itself."""
    output = payload.get("output", []) if isinstance(payload, dict) else []
    items = output if isinstance(output, list) else []
    text_chars = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content", [])
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_chars += len(part["text"])
        elif isinstance(item.get("text"), str):
            text_chars += len(item["text"])
    return {"output_items": len(items), "output_text_chars": text_chars}


def probe_shine_response(api_key: str | None, model: str, *, client: httpx.Client | None = None) -> ProbeResult:
    """Make exactly one non-streaming POST; POST transport/status failures are never retried."""
    start = time.monotonic()
    if not api_key:
        return ProbeResult("shine.response", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), error=_error("config", "missing_api_key"))
    if _safe_bounded_text(model, MAX_MODEL_ID_CHARS) is None:
        return ProbeResult("shine.response", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), error=_error("config", "explicit_model_required"))
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT, headers={"Authorization": f"Bearer {api_key}"}, trust_env=False)
    request_body = {"model": model, "input": "Reply with READY.", "max_output_tokens": 20, "stream": False}
    try:
        try:
            with client.stream("POST", f"{SHINE_BASE_URL}/responses", json=request_body) as response:
                status = response.status_code
                request_id = _safe_request_id(response.headers)
                body = _read_limited(response)
        except httpx.TransportError:
            return ProbeResult("shine.response", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), error=_error("transport", "transport_error"))
        if body is None:
            return ProbeResult(
                "shine.response",
                "BLOCKED_EXTERNAL",
                status,
                _duration_ms(start),
                details=_retry_details(response) if status is not None and not 200 <= status < 300 else None,
                error=_error("response", "response_too_large"),
                x_request_id=request_id,
            )
        if not 200 <= status < 300:
            return ProbeResult(
                "shine.response",
                "BLOCKED_EXTERNAL",
                status,
                _duration_ms(start),
                details=_retry_details(response),
                error=_shine_error_from_body(body),
                x_request_id=request_id,
            )
        try:
            summary = _output_summary(json.loads(body))
        except ValueError:
            return ProbeResult("shine.response", "BLOCKED_EXTERNAL", status, _duration_ms(start), error=_error("response", "invalid_json"), x_request_id=request_id)
        return ProbeResult("shine.response", "PASS", status, _duration_ms(start), details=summary, x_request_id=request_id)
    finally:
        if own_client:
            client.close()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _namespace(tag: str) -> str | None:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else None


def parse_wsdl_operations(wsdl: bytes) -> set[str] | None:
    try:
        root = ET.fromstring(wsdl)
    except ET.ParseError:
        return None
    return {
        name
        for element in root.iter()
        if _local_name(element.tag) == "operation" and (name := element.attrib.get("name"))
    }


def parse_wsdl_soap_actions(wsdl: bytes) -> dict[str, str] | None:
    """Return one exact binding SOAPAction per allowlisted operation.

    A portType declaration is insufficient: only SOAP operation metadata inside
    a binding authorizes a live call. SOAP 1.1 and 1.2 bindings may repeat an
    identical action; distinct values are ambiguous and fail closed rather than
    selecting a protocol/version by guesswork.
    """
    try:
        root = ET.fromstring(wsdl)
    except ET.ParseError:
        return None
    candidates: dict[str, list[str]] = {}
    for binding in root.iter():
        if _local_name(binding.tag) != "binding":
            continue
        for operation in binding:
            if _local_name(operation.tag) != "operation":
                continue
            name = operation.attrib.get("name")
            if name not in VBQPPL_ALLOWLIST:
                continue
            actions = [
                child.attrib.get("soapAction")
                for child in operation
                if _namespace(child.tag) in SOAP_BINDING_NAMESPACES and _local_name(child.tag) == "operation" and child.attrib.get("soapAction")
            ]
            candidates.setdefault(name, []).extend(action for action in actions if action is not None)
    parsed: dict[str, str] = {}
    for operation in VBQPPL_ALLOWLIST:
        actions = set(candidates.get(operation, []))
        if len(actions) != 1:
            return None
        parsed[operation] = next(iter(actions))
    return parsed


def parse_wsdl_soap_endpoint(wsdl: bytes) -> str | None:
    """Return one HTTPS SOAP 1.1 service address from the inspected WSDL."""
    try:
        root = ET.fromstring(wsdl)
    except ET.ParseError:
        return None
    locations = {
        location
        for element in root.iter()
        if _namespace(element.tag) == SOAP11_BINDING_NAMESPACE
        and _local_name(element.tag) == "address"
        and (location := element.attrib.get("location"))
        and location.lower().startswith("https://")
    }
    return next(iter(locations)) if len(locations) == 1 else None


def _soap_envelope(body_xml: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP11_ENVELOPE_NAMESPACE}"><soap:Body>'
        + body_xml
        + "</soap:Body></soap:Envelope>"
    ).encode("utf-8")


def _known_document_discovery_body(document_number: str) -> str:
    """Build the sole permitted discovery request; no caller-controlled XML."""
    return (
        f'<GetListVanBanByListSKH xmlns="{VBQPPL_NAMESPACE}" xmlns:xsi="{XSI_NAMESPACE}">'
        f"<skh>{xml_escape(document_number)}</skh>"
        '<ngaybanhanh xsi:nil="true"/>'
        '<ngaycohieuluc xsi:nil="true"/>'
        "</GetListVanBanByListSKH>"
    )


def _known_document_detail_body(soap_document_id: int) -> str:
    return f'<GetVanBanById xmlns="{VBQPPL_NAMESPACE}"><ItemID>{soap_document_id}</ItemID></GetVanBanById>'


def _soap_post_once(client: httpx.Client, soap_url: str, soap_action: str, body_xml: str) -> tuple[int | None, bytes | None, dict[str, str] | None]:
    """One bounded SOAP 1.1 POST.  Redirects and retries are never followed."""
    try:
        with client.stream(
            "POST",
            soap_url,
            content=_soap_envelope(body_xml),
            headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{soap_action}"'},
            follow_redirects=False,
        ) as response:
            body = _read_limited(response)
            return response.status_code, body, None if body is not None else _error("response", "response_too_large")
    except httpx.TransportError:
        return None, None, _error("transport", "transport_error")


def _soap_fault(xml: bytes) -> tuple[bool, str | None]:
    """Extract only a bounded SOAP fault code, never fault text or XML."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False, None
    faults = [element for element in root.iter() if _local_name(element.tag) == "Fault"]
    if not faults:
        return False, None
    codes = [
        (element.text or "").strip()
        for element in faults[0].iter()
        if _local_name(element.tag) in {"faultcode", "Code", "Value"} and (element.text or "").strip()
    ]
    code = codes[0] if codes else None
    if code is not None and (len(code) > MAX_ERROR_FIELD_CHARS or not re.fullmatch(r"[A-Za-z0-9_.:-]+", code)):
        code = "unavailable"
    return True, code


def _parse_xml(xml: bytes) -> ET.Element | None:
    try:
        return ET.fromstring(xml)
    except ET.ParseError:
        return None


def _positive_soap_id(value: str) -> int | None:
    if not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        return None
    parsed = int(value)
    return parsed if parsed <= 2_147_483_647 else None


def _discovery_selection(xml: bytes, document_number: str) -> tuple[int, int, int | None] | None:
    """Return bounded item/signature facts and the selected legacy SOAP ID.

    The new public page identifier and the legacy SOAP ``VanBanItem.ID`` are
    separate namespaces.  Only a direct document-number signature selects an
    item; identifiers and metadata from all other items remain undisclosed.
    """
    root = _parse_xml(xml)
    if root is None:
        return None
    items: list[ET.Element] = []
    for item in root.iter():
        if _local_name(item.tag) != "VanBanItem":
            continue
        items.append(item)
        if len(items) == MAX_VBQPPL_ITEM_SCAN:
            break
    signature_matches = [
        item
        for item in items
        if any((node.text or "").strip() == document_number for node in item if _local_name(node.tag) == "VBPQSokyhieu")
    ]
    selected_soap_id: int | None = None
    if len(signature_matches) == 1:
        direct_ids = [(node.text or "").strip() for node in signature_matches[0] if _local_name(node.tag) == "ID"]
        if len(direct_ids) == 1:
            selected_soap_id = _positive_soap_id(direct_ids[0])
    return len(items), len(signature_matches), selected_soap_id


def _direct_detail_summary(xml: bytes, soap_document_id: int) -> tuple[bool, bool, bool, int] | None:
    """Read only the one direct result and return ID, metadata, content facts."""
    root = _parse_xml(xml)
    if root is None:
        return None
    results = [element for element in root.iter() if _local_name(element.tag) == "GetVanBanByIdResult"]
    if len(results) != 1:
        return None
    result = results[0]
    values: dict[str, list[str]] = {}
    direct_ids = [(element.text or "").strip() for element in result if _local_name(element.tag) == "ID"]
    for element in result.iter():
        name = _local_name(element.tag)
        if name in {"Title", "VBPQSokyhieu", "VBPQTrichYeu", "VBPQToanVan"}:
            values.setdefault(name, []).append((element.text or "").strip())
    id_matches = direct_ids.count(str(soap_document_id)) == 1
    metadata_present = any(any(value for value in values.get(name, [])) for name in ("Title", "VBPQSokyhieu", "VBPQTrichYeu"))
    content_values = [value for value in values.get("VBPQToanVan", []) if value]
    content = content_values[0] if len(content_values) == 1 else ""
    return id_matches, metadata_present, bool(content), min(len(content), MAX_RESPONSE_BYTES)


def _is_official_vbqppl_https(url: str) -> bool:
    """Insecure diagnostic TLS is restricted to this one HTTPS authority."""
    try:
        parts = urlsplit(url)
        return (
            parts.scheme.lower() == "https"
            and parts.hostname == VBQPPL_OFFICIAL_HOST
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
        )
    except ValueError:
        return False


def _vbqppl_diagnostic_details(*, tls_verified: bool, transport_reachable: bool, wsdl_parsed: bool = False, soap_actions_parsed: bool = False, live: bool = False) -> dict[str, Any]:
    return {
        "tls_verified": tls_verified,
        "diagnostic_transport_reachable": transport_reachable,
        "wsdl_parsed": wsdl_parsed,
        "soap_actions_parsed": soap_actions_parsed,
        "live": live,
    }


def parse_tls_verify_config(value: str | None) -> bool | None:
    """Return the strict dotenv TLS setting, defaulting to secure verification."""

    if value is None:
        return True
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _functional_details(*, tls_verified: bool, discovery_status: int | None = None, detail_status: int | None = None, discovery_duration_ms: int | None = None, detail_duration_ms: int | None = None, discovery_calls: int = 0, detail_calls: int = 0, discovery_item_count: int = 0, signature_match_count: int = 0, selected_soap_id_present: bool = False, public_id_matches_soap_id: bool = False, discovery_pass: bool = False, detail_pass: bool = False, metadata_present: bool = False, content_present: bool = False, content_chars: int = 0, discovery_fault_present: bool = False, discovery_fault_code: str | None = None, detail_fault_present: bool = False, detail_fault_code: str | None = None) -> dict[str, Any]:
    return {
        "tls_verified": tls_verified,
        "discovery_pass": discovery_pass,
        "detail_pass": detail_pass,
        "metadata_present": metadata_present,
        "content_present": content_present,
        "content_chars": min(max(content_chars, 0), MAX_RESPONSE_BYTES),
        "discovery_status": discovery_status,
        "detail_status": detail_status,
        "discovery_duration_ms": discovery_duration_ms,
        "detail_duration_ms": detail_duration_ms,
        "discovery_calls": discovery_calls,
        "detail_calls": detail_calls,
        "discovery_item_count": min(max(discovery_item_count, 0), MAX_VBQPPL_ITEM_SCAN),
        "signature_match_count": min(max(signature_match_count, 0), MAX_VBQPPL_ITEM_SCAN),
        "selected_soap_id_present": selected_soap_id_present,
        "public_id_matches_soap_id": public_id_matches_soap_id,
        "discovery_fault_present": discovery_fault_present,
        "discovery_fault_code": discovery_fault_code,
        "detail_fault_present": detail_fault_present,
        "detail_fault_code": detail_fault_code,
        "functional_read_pass": discovery_pass and detail_pass and metadata_present and content_present,
    }


def _valid_known_document_inputs(document_number: str | None, public_document_id: int | None) -> bool:
    return (
        isinstance(document_number, str)
        and len(document_number) <= MAX_VBQPPL_DOCUMENT_NUMBER_CHARS
        and VBQPPL_DOCUMENT_NUMBER_PATTERN.fullmatch(document_number) is not None
        and (
            public_document_id is None
            or (isinstance(public_document_id, int) and not isinstance(public_document_id, bool) and 0 < public_document_id <= 2_147_483_647)
        )
    )


def probe_vbqppl(
    wsdl_url: str,
    *,
    live_known_document: bool = False,
    document_number: str | None = None,
    expected_document_id: int | None = None,
    insecure_tls: bool = False,
    client: httpx.Client | None = None,
) -> ProbeResult:
    """Verify WSDL, then optionally execute the one fixed read-only workflow.

    ``expected_document_id`` is retained for CLI/API compatibility as a public
    page reference only.  It is never used to select the legacy SOAP record.
    """
    start = time.monotonic()
    diagnostic = _vbqppl_diagnostic_details(tls_verified=not insecure_tls, transport_reachable=False, live=live_known_document)
    if not wsdl_url.lower().startswith("https://"):
        failure_details = _functional_details(tls_verified=not insecure_tls) if live_known_document else (diagnostic if insecure_tls else None)
        return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), details=failure_details, error=_error("tls", "https_required"))
    if insecure_tls and not _is_official_vbqppl_https(wsdl_url):
        failure_details = _functional_details(tls_verified=False) if live_known_document else diagnostic
        return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), details=failure_details, error=_error("tls", "insecure_tls_host_not_allowed"))
    if live_known_document and not _valid_known_document_inputs(document_number, expected_document_id):
        return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), details=_functional_details(tls_verified=not insecure_tls), error=_error("config", "invalid_known_document_input"))
    own_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT, verify=not insecure_tls, follow_redirects=False)
    try:
        # WSDL retrieval is deliberately one attempt: it gates all SOAP calls.
        try:
            with client.stream("GET", wsdl_url, follow_redirects=False) as response:
                status = response.status_code
                wsdl = _read_limited(response)
                error = None if wsdl is not None else _error("response", "response_too_large")
        except httpx.TransportError:
            status, wsdl, error = None, None, _error("transport", "transport_error")
        diagnostic["diagnostic_transport_reachable"] = status is not None
        if error or status != 200 or wsdl is None:
            failure_details = _functional_details(tls_verified=not insecure_tls) if live_known_document else (diagnostic if insecure_tls else None)
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", status, _duration_ms(start), details=failure_details, error=error or _error("wsdl", "wsdl_unavailable"))
        operations = parse_wsdl_operations(wsdl)
        if operations is None:
            failure_details = _functional_details(tls_verified=not insecure_tls) if live_known_document else (diagnostic if insecure_tls else None)
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", status, _duration_ms(start), details=failure_details, error=_error("wsdl", "invalid_wsdl"))
        diagnostic["wsdl_parsed"] = True
        if not VBQPPL_ALLOWLIST.issubset(operations):
            details: dict[str, Any] = _functional_details(tls_verified=not insecure_tls) if live_known_document else {"required_operations": sorted(VBQPPL_ALLOWLIST)}
            if insecure_tls and not live_known_document:
                details.update(diagnostic)
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", status, _duration_ms(start), details=details, error=_error("wsdl", "allowlist_not_confirmed"))
        soap_actions = parse_wsdl_soap_actions(wsdl)
        if soap_actions is None:
            failure_details = _functional_details(tls_verified=not insecure_tls) if live_known_document else (diagnostic if insecure_tls else None)
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", status, _duration_ms(start), details=failure_details, error=_error("wsdl", "soap_action_not_established"))
        diagnostic["soap_actions_parsed"] = True
        if not live_known_document:
            if insecure_tls:
                return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", status, _duration_ms(start), details=diagnostic, error=_error("tls", "insecure_diagnostic"))
            return ProbeResult("vbqppl", "PASS", status, _duration_ms(start), details={"required_operations": sorted(VBQPPL_ALLOWLIST), "live": False})
        soap_url = parse_wsdl_soap_endpoint(wsdl)
        if soap_url is None or (insecure_tls and not _is_official_vbqppl_https(soap_url)):
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", status, _duration_ms(start), details=_functional_details(tls_verified=not insecure_tls), error=_error("wsdl", "soap_endpoint_not_established"))
        assert document_number is not None
        public_document_id = expected_document_id
        discovery_start = time.monotonic()
        discovery_status, discovery_response, soap_error = _soap_post_once(client, soap_url, soap_actions["GetListVanBanByListSKH"], _known_document_discovery_body(document_number))
        discovery_duration = _duration_ms(discovery_start)
        discovery_fault, discovery_fault_code = _soap_fault(discovery_response) if discovery_response is not None else (False, None)
        selection = _discovery_selection(discovery_response, document_number) if discovery_response is not None else None
        discovery_item_count, signature_match_count, selected_soap_id = selection or (0, 0, None)
        public_id_matches_soap_id = public_document_id is not None and selected_soap_id == public_document_id
        discovery_pass = bool(not soap_error and discovery_status is not None and 200 <= discovery_status < 300 and not discovery_fault and signature_match_count == 1 and selected_soap_id is not None)
        details = _functional_details(tls_verified=not insecure_tls, discovery_status=discovery_status, discovery_duration_ms=discovery_duration, discovery_calls=1, discovery_item_count=discovery_item_count, signature_match_count=signature_match_count, selected_soap_id_present=selected_soap_id is not None, public_id_matches_soap_id=public_id_matches_soap_id, discovery_pass=discovery_pass, discovery_fault_present=discovery_fault, discovery_fault_code=discovery_fault_code)
        if not discovery_pass:
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", discovery_status, _duration_ms(start), details=details, error=_error("validation", "functional_read_failed"))
        assert selected_soap_id is not None
        detail_start = time.monotonic()
        detail_status, detail_response, soap_error = _soap_post_once(client, soap_url, soap_actions["GetVanBanById"], _known_document_detail_body(selected_soap_id))
        detail_duration = _duration_ms(detail_start)
        detail_fault, detail_fault_code = _soap_fault(detail_response) if detail_response is not None else (False, None)
        detail_summary = _direct_detail_summary(detail_response, selected_soap_id) if detail_response is not None else None
        id_match, metadata_present, content_present, content_chars = detail_summary or (False, False, False, 0)
        detail_pass = bool(not soap_error and detail_status is not None and 200 <= detail_status < 300 and not detail_fault and id_match and metadata_present and content_present)
        details = _functional_details(tls_verified=not insecure_tls, discovery_status=discovery_status, detail_status=detail_status, discovery_duration_ms=discovery_duration, detail_duration_ms=detail_duration, discovery_calls=1, detail_calls=1, discovery_item_count=discovery_item_count, signature_match_count=signature_match_count, selected_soap_id_present=True, public_id_matches_soap_id=public_id_matches_soap_id, discovery_pass=True, detail_pass=detail_pass, metadata_present=metadata_present, content_present=content_present, content_chars=content_chars, discovery_fault_present=discovery_fault, discovery_fault_code=discovery_fault_code, detail_fault_present=detail_fault, detail_fault_code=detail_fault_code)
        if not detail_pass:
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", detail_status, _duration_ms(start), details=details, error=_error("validation", "functional_read_failed"))
        if insecure_tls:
            return ProbeResult("vbqppl", "BLOCKED_EXTERNAL", detail_status, _duration_ms(start), details=details, error=_error("tls", "insecure_diagnostic"))
        return ProbeResult("vbqppl", "PASS", detail_status, _duration_ms(start), details=details)
    finally:
        if own_client:
            client.close()


@dataclass(frozen=True)
class _RestGatewayFacts:
    valid: bool
    metadata_present: bool
    updated_date_present: bool
    content_present: bool
    content_chars: int
    article_markup_present: bool


class _CanonicalLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return
        values = {name.lower(): value for name, value in attrs}
        rel = values.get("rel")
        href = values.get("href")
        if isinstance(rel, str) and isinstance(href, str) and "canonical" in rel.lower().split():
            self.hrefs.append(href)


def _nonempty_bounded_string(value: Any, limit: int = MAX_REST_RESPONSE_BYTES) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return value if 0 < len(value.encode("utf-8")) <= limit else None
    except UnicodeError:
        return None


def _rest_known_id_matches(value: Any) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool) and value == VBQPPL_REST_DOCUMENT_ID) or value == str(VBQPPL_REST_DOCUMENT_ID)


def _parse_rest_gateway(body: bytes) -> tuple[_RestGatewayFacts | None, dict[str, str] | None]:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None, _error("response", "invalid_gateway_json")
    if not isinstance(payload, dict):
        return None, _error("response", "invalid_gateway_json")
    data = payload.get("data")
    if not isinstance(data, dict):
        return _RestGatewayFacts(False, False, False, False, 0, False), None
    metadata_present = any(_nonempty_bounded_string(data.get(name), MAX_ERROR_FIELD_CHARS) is not None for name in ("title", "issueDate", "effFrom", "agencyName", "organization"))
    updated_date_present = _nonempty_bounded_string(data.get("updatedDate"), MAX_ERROR_FIELD_CHARS) is not None
    document_content = data.get("documentContent")
    content = _nonempty_bounded_string(document_content.get("content")) if isinstance(document_content, dict) else None
    content_chars = min(len(content), MAX_REST_RESPONSE_BYTES) if content is not None else 0
    article_markup_present = content is not None and "prov-article" in content
    html_content = content is not None and "<" in content and ">" in content
    valid = (
        payload.get("success") is True
        and type(payload.get("statusCode")) is int
        and payload["statusCode"] == 200
        and _rest_known_id_matches(data.get("id"))
        and data.get("docNum") == VBQPPL_REST_DOCUMENT_NUMBER
        and metadata_present
        and updated_date_present
        and data.get("hasContent") is True
        and html_content
    )
    return _RestGatewayFacts(valid, metadata_present, updated_date_present, html_content, content_chars, article_markup_present), None


def _canonical_match(html: bytes) -> bool:
    try:
        parser = _CanonicalLinkParser()
        parser.feed(html.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError):
        return False
    return len(parser.hrefs) == 1 and parser.hrefs[0] == VBQPPL_CANONICAL_PAGE_URL


def _rest_get_once(client: httpx.Client, url: str, *, headers: Mapping[str, str] | None = None) -> tuple[int | None, bytes | None, dict[str, str] | None]:
    """One bounded unauthenticated GET without redirects or retries."""
    try:
        with client.stream("GET", url, headers=headers, follow_redirects=False) as response:
            body = _read_limited(response, MAX_REST_RESPONSE_BYTES)
            return response.status_code, body, None if body is not None else _error("response", "response_too_large")
    except httpx.TransportError:
        return None, None, _error("transport", "transport_error")


def _rest_details(*, gateway_status: int | None = None, page_status: int | None = None, gateway_duration_ms: int | None = None, page_duration_ms: int | None = None, gateway_calls: int = 0, page_calls: int = 0, metadata_present: bool = False, updated_date_present: bool = False, content_present: bool = False, content_chars: int = 0, article_markup_present: bool = False, canonical_match: bool = False, functional_read_pass: bool = False) -> dict[str, Any]:
    return {
        "fallback_transport": VBQPPL_REST_TRANSPORT,
        "tls_verified": True,
        "gateway_status": gateway_status,
        "page_status": page_status,
        "gateway_duration_ms": gateway_duration_ms,
        "page_duration_ms": page_duration_ms,
        "gateway_calls": gateway_calls,
        "page_calls": page_calls,
        "metadata_present": metadata_present,
        "updated_date_present": updated_date_present,
        "content_present": content_present,
        "content_chars": min(max(content_chars, 0), MAX_REST_RESPONSE_BYTES),
        "article_markup_present": article_markup_present,
        "canonical_match": canonical_match,
        "functional_read_pass": functional_read_pass,
    }


def probe_vbqppl_rest_known_document(*, document_id: int = VBQPPL_REST_DOCUMENT_ID, document_number: str = VBQPPL_REST_DOCUMENT_NUMBER, canonical_url: str = VBQPPL_CANONICAL_PAGE_URL, client: httpx.Client | None = None) -> ProbeResult:
    """Measure the fixed, read-only current-frontend REST document path."""
    start = time.monotonic()
    if type(document_id) is not int or document_id != VBQPPL_REST_DOCUMENT_ID or document_number != VBQPPL_REST_DOCUMENT_NUMBER or canonical_url != VBQPPL_CANONICAL_PAGE_URL:
        return ProbeResult("vbqppl.rest", "BLOCKED_EXTERNAL", duration_ms=_duration_ms(start), details=_rest_details(), error=_error("config", "invalid_known_document_input"))
    own_client = client is None
    client = client or httpx.Client(timeout=REST_TIMEOUT, verify=True, follow_redirects=False)
    try:
        gateway_start = time.monotonic()
        gateway_status, gateway_body, gateway_error = _rest_get_once(client, VBQPPL_REST_GATEWAY_URL)
        gateway_duration = _duration_ms(gateway_start)
        if gateway_error or gateway_status != 200 or gateway_body is None:
            return ProbeResult("vbqppl.rest", "BLOCKED_EXTERNAL", gateway_status, _duration_ms(start), details=_rest_details(gateway_status=gateway_status, gateway_duration_ms=gateway_duration, gateway_calls=1), error=gateway_error or _error("http", "gateway_http_status"))
        gateway_facts, parse_error = _parse_rest_gateway(gateway_body)
        if parse_error or gateway_facts is None:
            return ProbeResult("vbqppl.rest", "BLOCKED_EXTERNAL", gateway_status, _duration_ms(start), details=_rest_details(gateway_status=gateway_status, gateway_duration_ms=gateway_duration, gateway_calls=1), error=parse_error or _error("response", "invalid_gateway_json"))
        gateway_details = _rest_details(gateway_status=gateway_status, gateway_duration_ms=gateway_duration, gateway_calls=1, metadata_present=gateway_facts.metadata_present, updated_date_present=gateway_facts.updated_date_present, content_present=gateway_facts.content_present, content_chars=gateway_facts.content_chars, article_markup_present=gateway_facts.article_markup_present)
        if not gateway_facts.valid:
            return ProbeResult("vbqppl.rest", "BLOCKED_EXTERNAL", gateway_status, _duration_ms(start), details=gateway_details, error=_error("validation", "functional_read_failed"))
        page_start = time.monotonic()
        page_status, page_body, page_error = _rest_get_once(client, VBQPPL_CANONICAL_PAGE_URL, headers=VBQPPL_CANONICAL_PAGE_HEADERS)
        page_duration = _duration_ms(page_start)
        if page_error or page_status != 200 or page_body is None:
            return ProbeResult("vbqppl.rest", "BLOCKED_EXTERNAL", page_status, _duration_ms(start), details=_rest_details(gateway_status=gateway_status, page_status=page_status, gateway_duration_ms=gateway_duration, page_duration_ms=page_duration, gateway_calls=1, page_calls=1, metadata_present=gateway_facts.metadata_present, updated_date_present=gateway_facts.updated_date_present, content_present=gateway_facts.content_present, content_chars=gateway_facts.content_chars, article_markup_present=gateway_facts.article_markup_present), error=page_error or _error("http", "page_http_status"))
        canonical_match = _canonical_match(page_body)
        functional_pass = gateway_facts.valid and canonical_match
        details = _rest_details(gateway_status=gateway_status, page_status=page_status, gateway_duration_ms=gateway_duration, page_duration_ms=page_duration, gateway_calls=1, page_calls=1, metadata_present=gateway_facts.metadata_present, updated_date_present=gateway_facts.updated_date_present, content_present=gateway_facts.content_present, content_chars=gateway_facts.content_chars, article_markup_present=gateway_facts.article_markup_present, canonical_match=canonical_match, functional_read_pass=functional_pass)
        if not functional_pass:
            return ProbeResult("vbqppl.rest", "BLOCKED_EXTERNAL", page_status, _duration_ms(start), details=details, error=_error("validation", "functional_read_failed"))
        return ProbeResult("vbqppl.rest", "PASS", page_status, _duration_ms(start), details=details)
    finally:
        if own_client:
            client.close()


def _main(argv: list[str] | None = None, *, dotenv_path: Path | None = None) -> int:
    load_repo_env(dotenv_path)
    parser = argparse.ArgumentParser(description="M00 external integration probes")
    commands = parser.add_subparsers(dest="command", required=True)
    models = commands.add_parser("shine-models")
    models.add_argument("--model")
    response = commands.add_parser("shine-response")
    response.add_argument("--model", required=True)
    vbqppl = commands.add_parser("vbqppl")
    vbqppl.add_argument("--wsdl-url", required=True)
    vbqppl.add_argument("--insecure-tls", action="store_true", help="diagnostic only; restricted to official HTTPS WSDL host")
    vbqppl.add_argument("--live-known-document", action="store_true", help="perform the fixed read-only known-document measurement")
    vbqppl.add_argument("--document-number")
    vbqppl.add_argument("--expected-document-id", type=int)
    vbqppl_rest = commands.add_parser("vbqppl-rest-known-document")
    vbqppl_rest.add_argument("--document-id", type=int, default=VBQPPL_REST_DOCUMENT_ID)
    vbqppl_rest.add_argument("--document-number", default=VBQPPL_REST_DOCUMENT_NUMBER)
    vbqppl_rest.add_argument("--canonical-url", default=VBQPPL_CANONICAL_PAGE_URL)
    args = parser.parse_args(argv)
    if args.command == "shine-models":
        result = probe_shine_models(os.environ.get("SHINE_API_KEY"), args.model)
    elif args.command == "shine-response":
        result = probe_shine_response(os.environ.get("SHINE_API_KEY"), args.model)
    elif args.command == "vbqppl":
        tls_verify = parse_tls_verify_config(os.environ.get("VBQPPL_TLS_VERIFY"))
        if tls_verify is None:
            result = ProbeResult("vbqppl", "BLOCKED_EXTERNAL", error=_error("config", "invalid_tls_verify_config"))
        else:
            result = probe_vbqppl(
                args.wsdl_url,
                live_known_document=args.live_known_document,
                document_number=args.document_number,
                expected_document_id=args.expected_document_id,
                insecure_tls=args.insecure_tls or not tls_verify,
            )
    elif args.command == "vbqppl-rest-known-document":
        result = probe_vbqppl_rest_known_document(document_id=args.document_id, document_number=args.document_number, canonical_url=args.canonical_url)
    else:
        raise AssertionError("unreachable command")
    print(result.to_json())
    return 0 if result.outcome == "PASS" else 2


if __name__ == "__main__":
    sys.exit(_main())
