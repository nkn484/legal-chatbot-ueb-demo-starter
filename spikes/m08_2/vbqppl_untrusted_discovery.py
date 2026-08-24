"""One-off, untrusted TLS diagnostic for the manifest-approved VBQPPL SOAP discovery set.

This spike is intentionally not a legal-source adapter. Its output is an UNTRUSTED
review artifact and cannot authorize fetching, ingestion, or citation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

import httpx

from legal_chatbot.sources.registry import load_manifest

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[2]
MANIFEST_RELATIVE_PATH: Final = Path("contracts/vbqppl-read-manifest.json")
_REVIEWED_MANIFEST_RELATIVE_PATH: Final = Path("contracts/vbqppl-read-manifest.json")
ARTIFACT_RELATIVE_PATH: Final = Path("docs/evidence/M08.2-vbqppl-untrusted-discovery.json")
_REVIEWED_ARTIFACT_RELATIVE_PATH: Final = Path(
    "docs/evidence/M08.2-vbqppl-untrusted-discovery.json"
)
WSDL_URL: Final = "https://ws.vbpl.vn/vbqppl.asmx?WSDL"
POST_URL: Final = "https://ws.vbpl.vn/vbqppl.asmx"
SOAP_ACTION: Final = "http://tempuri.org/GetListVanBanByListSKH"
VBQPPL_NAMESPACE: Final = "http://tempuri.org/"
SOAP_ENVELOPE_NAMESPACE: Final = "http://schemas.xmlsoap.org/soap/envelope/"
EXPECTED_REQUEST_COUNT: Final = 32
MAX_RESPONSE_BYTES: Final = 2_097_152
MAX_XML_NODES: Final = 2_048
MAX_XML_DEPTH: Final = 64
MAX_DISCOVERED_ID: Final = 2_147_483_647
ARTIFACT_VERSION: Final = "m08_2_untrusted_discovery_v1"


class DiagnosticCode(StrEnum):
    """Fixed, content-safe diagnostic result codes."""

    ACCESS_DENIED = "access_denied"
    DOCUMENT_NOT_FOUND = "document_not_found"
    INVALID_RESPONSE = "invalid_response"
    MANIFEST_INVALID = "manifest_invalid"
    PRECONDITION_FAILED = "precondition_failed"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class UntrustedCandidate:
    """Opaque discovery identity that deliberately has no fetch capability fields."""

    document_number: str
    discovered_id: str


@dataclass(frozen=True)
class DiagnosticOutcome:
    """One safe result for one manifest-derived document number."""

    document_number: str
    candidate: UntrustedCandidate | None = None
    error: DiagnosticCode | None = None

    def __post_init__(self) -> None:
        if (self.candidate is None) == (self.error is None):
            raise ValueError("diagnostic outcome requires one candidate or one error")
        if self.candidate is not None and self.candidate.document_number != self.document_number:
            raise ValueError("candidate number must match outcome number")

    def payload(self) -> dict[str, object]:
        base: dict[str, object] = {
            "citation_allowed": False,
            "document_number": self.document_number,
            "fetch_allowed": False,
            "ingestion_allowed": False,
            "tls_verified": False,
            "trust_level": "UNTRUSTED",
        }
        if self.candidate is not None:
            base["outcome"] = "success"
            base["candidate"] = asdict(self.candidate)
        else:
            base["error"] = (
                self.error.value if self.error is not None else DiagnosticCode.UNAVAILABLE
            )
            base["outcome"] = "failure"
        return base


@dataclass
class NetworkCounts:
    wsdl_get: int = 0
    soap_post: int = 0

    def payload(self) -> dict[str, int]:
        return {
            "soap_post": self.soap_post,
            "total": self.wsdl_get + self.soap_post,
            "wsdl_get": self.wsdl_get,
        }


class _DiagnosticFailure(Exception):
    def __init__(self, code: DiagnosticCode) -> None:
        self.code = code
        super().__init__(code.value)


def _validate_static_targets() -> None:
    """Reject any local constant drift before constructing a network client."""
    if (
        not _is_exact_target(WSDL_URL, wsdl=True)
        or not _is_exact_target(POST_URL, wsdl=False)
        or SOAP_ACTION != "http://tempuri.org/GetListVanBanByListSKH"
        or VBQPPL_NAMESPACE != "http://tempuri.org/"
        or SOAP_ENVELOPE_NAMESPACE != "http://schemas.xmlsoap.org/soap/envelope/"
    ):
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)


def _is_exact_target(value: str, *, wsdl: bool) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "ws.vbpl.vn"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path == "/vbqppl.asmx"
            and parsed.query == ("WSDL" if wsdl else "")
            and not parsed.fragment
        )
    except ValueError:
        return False


def _is_link_or_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _resolve_reviewed_path(relative_path: Path, *, require_existing_file: bool) -> Path:
    """Resolve a fixed repository-relative regular file without link/reparse traversal."""
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    try:
        root = REPOSITORY_ROOT.resolve(strict=True)
    except OSError as error:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED) from error
    current = root
    for index, part in enumerate(relative_path.parts):
        current /= part
        is_target = index == len(relative_path.parts) - 1
        try:
            unsafe = _is_link_or_reparse_point(current)
        except OSError:
            if not is_target or require_existing_file:
                raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED) from None
            return current
        if unsafe or (not is_target and not current.is_dir()) or (is_target and current.is_dir()):
            raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
        if is_target and require_existing_file and not current.is_file():
            raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    return current


def _manifest_path() -> Path:
    if MANIFEST_RELATIVE_PATH != _REVIEWED_MANIFEST_RELATIVE_PATH:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    return _resolve_reviewed_path(MANIFEST_RELATIVE_PATH, require_existing_file=True)


def _artifact_path() -> Path:
    if ARTIFACT_RELATIVE_PATH != _REVIEWED_ARTIFACT_RELATIVE_PATH:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    return _resolve_reviewed_path(ARTIFACT_RELATIVE_PATH, require_existing_file=False)


def _load_requests(manifest_path: Path) -> tuple[str, ...]:
    """Load only the repository manifest through production's validated parser."""
    try:
        manifest = load_manifest(manifest_path)
        requests = manifest.discovery_requests()
    except Exception as error:
        raise _DiagnosticFailure(DiagnosticCode.MANIFEST_INVALID) from error
    if len(requests) != EXPECTED_REQUEST_COUNT or any(
        request.source_id != "VBQPPL" or request.transport != "SOAP" for request in requests
    ):
        raise _DiagnosticFailure(DiagnosticCode.MANIFEST_INVALID)
    return tuple(request.document_number for request in requests)


def _safe_xml_root(payload: bytes) -> ET.Element:
    if (
        len(payload) > MAX_RESPONSE_BYTES
        or b"<!DOCTYPE" in payload.upper()
        or b"<!ENTITY" in payload.upper()
    ):
        raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE) from error
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    nodes = 0
    while stack:
        element, depth = stack.pop()
        nodes += 1
        if nodes > MAX_XML_NODES or depth > MAX_XML_DEPTH:
            raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
        stack.extend((child, depth + 1) for child in element)
    return root


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _is_fault(root: ET.Element) -> bool:
    return any(_local_name(element.tag) == "Fault" for element in root.iter())


def _select_candidate(payload: bytes, document_number: str) -> UntrustedCandidate:
    root = _safe_xml_root(payload)
    if _is_fault(root):
        raise _DiagnosticFailure(DiagnosticCode.UNAVAILABLE)
    results = [
        element
        for element in root.iter()
        if _local_name(element.tag) == "GetListVanBanByListSKHResult"
    ]
    if len(results) != 1:
        raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
    matches: list[ET.Element] = []
    for item in results[0].iter():
        if _local_name(item.tag) != "VanBanItem":
            continue
        numbers = [
            (child.text or "").strip() for child in item if _local_name(child.tag) == "VBPQSokyhieu"
        ]
        if numbers.count(document_number) == 1:
            matches.append(item)
    if not matches:
        raise _DiagnosticFailure(DiagnosticCode.DOCUMENT_NOT_FOUND)
    if len(matches) != 1:
        raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
    identifiers = [
        (child.text or "").strip() for child in matches[0] if _local_name(child.tag) == "ID"
    ]
    if len(identifiers) != 1 or not re.fullmatch(r"[1-9][0-9]{0,9}", identifiers[0]):
        raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
    if int(identifiers[0]) > MAX_DISCOVERED_ID:
        raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
    return UntrustedCandidate(document_number=document_number, discovered_id=identifiers[0])


def _discovery_body(document_number: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP_ENVELOPE_NAMESPACE}"><soap:Body>'
        f'<GetListVanBanByListSKH xmlns="{VBQPPL_NAMESPACE}">'
        f"<skh>{xml_escape(document_number)}</skh>"
        "</GetListVanBanByListSKH></soap:Body></soap:Envelope>"
    ).encode()


async def _read_response(response: httpx.Response) -> bytes:
    if response.is_stream_consumed:
        payload = response.content
        if len(payload) > MAX_RESPONSE_BYTES:
            raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
        return payload
    body = bytearray()
    async for chunk in response.aiter_raw():
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise _DiagnosticFailure(DiagnosticCode.INVALID_RESPONSE)
    return bytes(body)


def _status_code(status_code: int, *, document: bool) -> DiagnosticCode:
    if status_code in {401, 403}:
        return DiagnosticCode.ACCESS_DENIED
    if status_code == 404 and document:
        return DiagnosticCode.DOCUMENT_NOT_FOUND
    if status_code in {408, 504}:
        return DiagnosticCode.TIMEOUT
    return DiagnosticCode.UNAVAILABLE


async def _request(
    client: httpx.AsyncClient,
    method: str,
    target: str,
    *,
    body: bytes | None,
    counts: NetworkCounts,
) -> bytes:
    is_wsdl = method == "GET"
    if method not in {"GET", "POST"} or not _is_exact_target(target, wsdl=is_wsdl):
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    if method == "GET" and body is not None:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    if method == "POST" and body is None:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    headers = (
        {
            "Accept": "text/xml",
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SOAP_ACTION}"',
        }
        if method == "POST"
        else {"Accept": "text/xml"}
    )
    if method == "GET":
        counts.wsdl_get += 1
    else:
        counts.soap_post += 1
    try:
        async with client.stream(
            method, target, content=body, headers=headers, follow_redirects=False
        ) as response:
            if response.is_redirect or response.status_code != 200:
                raise _DiagnosticFailure(
                    _status_code(response.status_code, document=method == "POST")
                )
            return await _read_response(response)
    except _DiagnosticFailure:
        raise
    except httpx.TimeoutException as error:
        raise _DiagnosticFailure(DiagnosticCode.TIMEOUT) from error
    except httpx.HTTPError as error:
        raise _DiagnosticFailure(DiagnosticCode.UNAVAILABLE) from error


def _build_client() -> httpx.AsyncClient:
    client = httpx.AsyncClient(verify=False, trust_env=False, follow_redirects=False, headers={})
    client.headers = httpx.Headers()
    return client


def _artifact(outcomes: Sequence[DiagnosticOutcome], counts: NetworkCounts) -> dict[str, object]:
    success_count = sum(outcome.candidate is not None for outcome in outcomes)
    return {
        "artifact_version": ARTIFACT_VERSION,
        "citation_allowed": False,
        "failure_count": len(outcomes) - success_count,
        "fetch_allowed": False,
        "ingestion_allowed": False,
        "network_calls": counts.payload(),
        "outcomes": [outcome.payload() for outcome in outcomes],
        "success_count": success_count,
        "tls_verified": False,
        "trust_level": "UNTRUSTED",
    }


def _write_artifact(artifact_path: Path, artifact: dict[str, object]) -> None:
    """Atomically replace only the fixed reviewed artifact with a new regular file."""
    if _artifact_path() != artifact_path:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
    encoded = (
        json.dumps(artifact, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    temporary_path = artifact_path.parent / f".{artifact_path.name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    try:
        descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        temporary_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(temporary_metadata.st_mode) or temporary_metadata.st_nlink > 1:
            raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
        with os.fdopen(descriptor, "wb") as temporary_file:
            descriptor = None
            temporary_file.write(encoded)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _validate_existing_artifact_target(artifact_path)
        if _artifact_path() != artifact_path:
            raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)
        _validate_existing_artifact_target(artifact_path)
        os.replace(temporary_path, artifact_path)
    except _DiagnosticFailure:
        raise
    except OSError as error:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _validate_existing_artifact_target(artifact_path: Path) -> None:
    """Reject target links, reparse points, directories, and multiply-linked files."""
    try:
        metadata = artifact_path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED) from error
    if (
        _is_link_or_reparse_point(artifact_path)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink > 1
    ):
        raise _DiagnosticFailure(DiagnosticCode.PRECONDITION_FAILED)


async def run_diagnostic(client_factory: Callable[[], httpx.AsyncClient] = _build_client) -> int:
    """Run the fixed diagnostic and write a complete, untrusted review artifact."""
    counts = NetworkCounts()
    try:
        _validate_static_targets()
        artifact_path = _artifact_path()
        manifest_path = _manifest_path()
        snapshot = manifest_path.read_bytes()
        numbers = _load_requests(manifest_path)
    except _DiagnosticFailure as error:
        try:
            _write_artifact(_artifact_path(), _artifact((), counts) | {"error": error.code.value})
        except _DiagnosticFailure:
            pass
        return 2

    client = client_factory()
    try:
        try:
            _safe_xml_root(await _request(client, "GET", WSDL_URL, body=None, counts=counts))
        except _DiagnosticFailure as error:
            outcomes = tuple(DiagnosticOutcome(number, error=error.code) for number in numbers)
        else:
            outcomes = []
            for number in numbers:
                try:
                    response = await _request(
                        client, "POST", POST_URL, body=_discovery_body(number), counts=counts
                    )
                    outcomes.append(
                        DiagnosticOutcome(number, candidate=_select_candidate(response, number))
                    )
                except _DiagnosticFailure as error:
                    outcomes.append(DiagnosticOutcome(number, error=error.code))
            outcomes = tuple(outcomes)
    finally:
        await client.aclose()

    if manifest_path.read_bytes() != snapshot:
        raise AssertionError("trusted manifest changed during diagnostic")
    artifact = _artifact(outcomes, counts)
    _write_artifact(artifact_path, artifact)
    return 1 if artifact["failure_count"] else 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        allow_abbrev=False, description="Run the fixed untrusted VBQPPL discovery diagnostic"
    )
    parser.add_argument("--acknowledge-untrusted-diagnostic", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.acknowledge_untrusted_diagnostic:
        parser.error("--acknowledge-untrusted-diagnostic is required")
    raise SystemExit(asyncio.run(run_diagnostic()))


if __name__ == "__main__":
    main()
