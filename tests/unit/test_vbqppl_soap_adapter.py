"""Safety coverage for manifest-gated VBQPPL SOAP discovery and fetch."""

import hashlib
import logging
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from legal_chatbot.sources.adapters.soap import VBQPPLSoapAdapter
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import SourceErrorCode
from legal_chatbot.sources.registry import load_manifest, load_registry


def settings(**changes: object) -> SourceSettings:
    values: dict[str, object] = {
        "VBQPPL_SOAP_CONNECT_TIMEOUT_SECONDS": 1,
        "VBQPPL_SOAP_RESPONSE_TIMEOUT_SECONDS": 1,
        "VBQPPL_SOAP_MAX_RESPONSE_BYTES": 1024,
        "VBQPPL_SOAP_TLS_VERIFY": True,
    }
    values.update(changes)
    return SourceSettings(**values)


def source():
    value = load_registry(Path("contracts/source-registry.json")).get("VBQPPL")
    assert value is not None
    return value.model_copy(update={"base_url": "https://soap.example.test/vbqppl.asmx"})


def manifest():
    return load_manifest(Path("contracts/vbqppl-read-manifest.json"))


def evolved_manifest(*, soap_fetch: bool = False, no_fetch: bool = False):
    baseline = manifest()
    payload = deepcopy(baseline.model_dump(mode="json"))
    if soap_fetch:
        payload["documents"][0]["fetch_permissions"][0] = {
            "transport": "SOAP",
            "status": "FETCH_APPROVED",
            "document_id": "200001",
            "detail_path": "/qtdc/public/doc/200001",
            "canonical_url": "https://vbpl.vn/van-ban/chi-tiet/future-soap--200001",
        }
    if no_fetch:
        payload["documents"][-1]["fetch_permissions"] = [
            {
                "transport": "SOAP",
                "status": "PENDING_EXACT_ID",
                "document_id": None,
                "detail_path": None,
                "canonical_url": None,
            },
            {
                "transport": "REST_FRONTEND_BACKING_API",
                "status": "NOT_APPROVED",
                "document_id": None,
                "detail_path": None,
                "canonical_url": None,
            },
        ]
    return type(baseline).model_validate(payload)


def wsdl() -> bytes:
    return b"""<definitions xmlns:soap="http://schemas.xmlsoap.org/wsdl/soap/">
      <binding name="soap11">
      <operation name="GetListVanBanByListSKH"><soap:operation soapAction="http://tempuri.org/GetListVanBanByListSKH"/></operation>
      <operation name="GetVanBanById"><soap:operation soapAction="http://tempuri.org/GetVanBanById"/></operation>
      </binding><service><port><soap:address location="https://soap.example.test/vbqppl.asmx"/></port></service></definitions>"""


def discovery(number: str, item_id: str = "8675309") -> bytes:
    return (
        f"<GetListVanBanByListSKHResult><VanBanItem><ID>{item_id}</ID>"
        f"<VBPQSokyhieu>{number}</VBPQSokyhieu></VanBanItem></GetListVanBanByListSKHResult>"
    ).encode()


def detail(item_id: str = "175258", content: str = "<article>law text</article>") -> bytes:
    return f"""<GetVanBanByIdResponse><GetVanBanByIdResult><ID>{item_id}</ID>
      <Title>Safe title</Title><VBPQSokyhieu>63/2025/QH15</VBPQSokyhieu>
      <VBPQToanVan><![CDATA[{content}]]></VBPQToanVan>
      </GetVanBanByIdResult></GetVanBanByIdResponse>""".encode()


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_list_is_fetch_approved_only_and_performs_zero_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        assert await adapter.list_documents() == manifest().fetch_refs("SOAP")
    assert calls == 0


@pytest.mark.asyncio
async def test_list_supports_evolved_multiple_or_zero_soap_fetch_refs_without_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    multiple = evolved_manifest(soap_fetch=True)
    empty = evolved_manifest(no_fetch=True)
    async with client(handler) as http_client:
        multiple_adapter = VBQPPLSoapAdapter(settings(), source(), http_client, multiple)
        empty_adapter = VBQPPLSoapAdapter(settings(), source(), http_client, empty)
        assert await multiple_adapter.list_documents() == multiple.fetch_refs("SOAP")
        assert await empty_adapter.list_documents() == ()

    assert len(multiple.fetch_refs("SOAP")) == 2
    assert calls == 0


@pytest.mark.asyncio
async def test_fetch_uses_only_exact_soap_ref_and_revalidates_identity() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=wsdl() if request.method == "GET" else detail())

    async with client(handler) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        snapshot = await adapter.fetch_document((await adapter.list_documents())[0])

    assert [request.method for request in calls] == ["GET", "POST"]
    assert calls[1].headers["SOAPAction"] == '"http://tempuri.org/GetVanBanById"'
    assert "<ItemID>175258</ItemID>" in calls[1].content.decode()
    assert snapshot.content_sha256 == hashlib.sha256(b"<article>law text</article>").hexdigest()


@pytest.mark.asyncio
async def test_discovery_is_exact_number_only_and_candidate_cannot_fetch() -> None:
    calls: list[httpx.Request] = []
    request = next(
        value
        for value in manifest().discovery_requests()
        if value.document_number == "125/2025/QH15"
    )

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(
            200,
            content=wsdl() if http_request.method == "GET" else discovery(request.document_number),
        )

    async with client(handler) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        candidate = await adapter.discover_document(request)
        with pytest.raises(SourceError) as denied:
            await adapter.fetch_document(candidate)  # type: ignore[arg-type]

    assert candidate.document_number == request.document_number
    assert candidate.external_id == "8675309"
    assert denied.value.code is SourceErrorCode.DOCUMENT_NOT_ALLOWED
    assert [request.method for request in calls] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_sequential_discovery_uses_one_instance_local_wsdl_and_never_fetches() -> None:
    calls: list[httpx.Request] = []
    requests = manifest().discovery_requests()[:2]

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        if http_request.method == "GET":
            return httpx.Response(200, content=wsdl())
        body = http_request.content.decode()
        number = next(
            request.document_number for request in requests if request.document_number in body
        )
        return httpx.Response(200, content=discovery(number))

    async with client(handler) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        candidates = [await adapter.discover_document(request) for request in requests]

    assert [candidate.document_number for candidate in candidates] == [
        request.document_number for request in requests
    ]
    assert [request.method for request in calls] == ["GET", "POST", "POST"]
    assert all("GetVanBanById" not in request.content.decode() for request in calls[1:])


@pytest.mark.asyncio
async def test_soap_and_rest_permissions_are_not_interchangeable_pre_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        with pytest.raises(SourceError) as denied:
            await adapter.fetch_document(manifest().fetch_refs("REST_FRONTEND_BACKING_API")[0])
    assert denied.value.code is SourceErrorCode.DOCUMENT_NOT_ALLOWED
    assert calls == 0


@pytest.mark.asyncio
async def test_soap_denies_mutated_fetch_capability_before_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        altered = manifest().fetch_refs("SOAP")[0].model_copy(update={"external_id": "175259"})
        with pytest.raises(SourceError) as denied:
            await adapter.fetch_document(altered)

    assert denied.value.code is SourceErrorCode.DOCUMENT_NOT_ALLOWED
    assert calls == 0


@pytest.mark.asyncio
async def test_discovery_failures_and_logs_do_not_leak_remote_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinel = "private SOAP body"
    caplog.set_level(logging.INFO, logger="legal_chatbot")
    request = manifest().discovery_requests()[0]

    async with client(
        lambda http_request: httpx.Response(
            200, content=wsdl() if http_request.method == "GET" else sentinel.encode()
        )
    ) as http_client:
        adapter = VBQPPLSoapAdapter(settings(), source(), http_client, manifest())
        with pytest.raises(SourceError) as error:
            await adapter.discover_document(request)

    assert error.value.code is SourceErrorCode.INVALID_RESPONSE
    assert sentinel not in "\n".join(str(record.__dict__) for record in caplog.records)
