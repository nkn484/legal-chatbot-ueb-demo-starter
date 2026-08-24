"""Unit coverage for the bounded VBQPPL REST fallback adapter."""

import hashlib
import logging
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from legal_chatbot.sources.adapters.rest import VBQPPLRestAdapter
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import SourceDocumentRef, SourceErrorCode, SourceHealthStatus
from legal_chatbot.sources.registry import load_manifest, load_registry

DETAIL_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/175258"
CANONICAL_URL = "https://vbpl.vn/van-ban/chi-tiet/luat-to-chuc-chinh-phu-so-63-2025-qh15--175258"
SENTINEL = "sentinel-private-vbqppl-payload"


def settings(**overrides: object) -> SourceSettings:
    values: dict[str, object] = {
        "rest_connect_timeout_seconds": 1.0,
        "rest_response_timeout_seconds": 2.0,
        "rest_max_response_bytes": 1024,
        "rest_max_attempts": 3,
        "rest_retry_max_seconds": 2.0,
    }
    values.update(overrides)
    return SourceSettings(**values)


def source():
    value = load_registry(settings().registry_path).get("VBQPPL")
    assert value is not None
    return value


def manifest():
    return load_manifest(settings().vbqppl_read_manifest_path)


def evolved_manifest(*, rest_fetch: bool = False, no_fetch: bool = False):
    baseline = manifest()
    payload = deepcopy(baseline.model_dump(mode="json"))
    if rest_fetch:
        payload["documents"][0]["fetch_permissions"][1] = {
            "transport": "REST_FRONTEND_BACKING_API",
            "status": "FETCH_APPROVED",
            "document_id": "175259",
            "detail_path": "/qtdc/public/doc/175259",
            "canonical_url": "https://vbpl.vn/van-ban/chi-tiet/future-rest--175259",
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


def client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def payload(**data_overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "175258",
        "docNum": "63/2025/QH15",
        "title": "Luật mẫu",
        "docType": {"name": "Luật"},
        "organization": {"name": "Quốc hội"},
        "issueDate": "2025-01-01",
        "effFrom": "2025-02-01T07:00:00+07:00",
        "effTo": "2030-01-01",
        "effStatus": {"name": "Còn hiệu lực"},
        "updatedDate": "2025-01-03T00:00:00Z",
        "hasContent": True,
        "documentContent": {"content": "<article>nội dung</article>"},
    }
    data.update(data_overrides)
    return {"success": True, "statusCode": 200, "data": data}


def canonical_html(url: str = CANONICAL_URL) -> bytes:
    return f"<html><head><link rel='canonical' href='{url}'></head></html>".encode()


@pytest.mark.asyncio
async def test_list_returns_current_manifest_refs_without_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        refs = await VBQPPLRestAdapter(settings(), source(), client=http_client).list_documents()

    assert refs == manifest().fetch_refs("REST_FRONTEND_BACKING_API")
    assert calls == 0


@pytest.mark.asyncio
async def test_rest_uses_each_evolved_manifest_ref_exact_path_and_canonical_url() -> None:
    evolved = evolved_manifest(rest_fetch=True)
    refs = evolved.fetch_refs("REST_FRONTEND_BACKING_API")
    future_ref = refs[0]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if str(request.url).endswith(future_ref.detail_path):
            return httpx.Response(
                200,
                json=payload(id=future_ref.external_id, docNum=future_ref.document_number),
            )
        return httpx.Response(200, content=canonical_html(future_ref.canonical_url or ""))

    async with client(handler) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client, manifest=evolved)
        assert await adapter.list_documents() == refs
        snapshot = await adapter.fetch_document(future_ref)

    assert len(refs) == 2
    assert [str(request.url) for request in calls] == [
        f"{DETAIL_URL[:-6]}175259",
        future_ref.canonical_url,
    ]
    assert snapshot.external_id == future_ref.external_id
    assert snapshot.canonical_url == future_ref.canonical_url


@pytest.mark.asyncio
async def test_rest_accepts_zero_fetch_refs_without_network() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        adapter = VBQPPLRestAdapter(
            settings(), source(), client=http_client, manifest=evolved_manifest(no_fetch=True)
        )
        assert await adapter.list_documents() == ()

    assert calls == 0


@pytest.mark.asyncio
async def test_fetch_blocks_any_nonexact_reference_before_http() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    arbitrary = SourceDocumentRef(
        source_id="VBQPPL",
        external_id="other",
        document_number="63/2025/QH15",
        canonical_url=CANONICAL_URL,
    )
    async with client(handler) as http_client:
        with pytest.raises(SourceError) as raised:
            adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
            await adapter.fetch_document(arbitrary)

    assert raised.value.code is SourceErrorCode.DOCUMENT_NOT_ALLOWED
    assert raised.value.status_code == 400
    assert calls == 0


@pytest.mark.asyncio
async def test_rest_rejects_the_separately_approved_soap_reference_before_http() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async with client(handler) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client, manifest=manifest())
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document(manifest().fetch_refs("SOAP")[0])

    assert raised.value.code is SourceErrorCode.DOCUMENT_NOT_ALLOWED
    assert calls == 0


@pytest.mark.asyncio
async def test_fetch_uses_exact_get_urls_headers_no_auth_body_or_redirects() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if str(request.url) == DETAIL_URL:
            return httpx.Response(200, json=payload())
        return httpx.Response(200, content=canonical_html())

    async with client(handler) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        snapshot = await adapter.fetch_document((await adapter.list_documents())[0])

    assert snapshot.source_id == "VBQPPL"
    assert [request.method for request in calls] == ["GET", "GET"]
    assert [str(request.url) for request in calls] == [DETAIL_URL, CANONICAL_URL]
    assert calls[0].headers["host"] == "vbpl-bientap-gateway.moj.gov.vn"
    assert calls[0].headers["accept"] == "application/json"
    assert "user-agent" not in calls[0].headers
    assert calls[1].headers["host"] == "vbpl.vn"
    assert calls[1].headers["accept"] == "text/html"
    assert calls[1].headers["user-agent"] == "legal-chatbot-ueb-demo-m03/1.0"
    assert all(
        "authorization" not in request.headers and request.content == b"" for request in calls
    )


@pytest.mark.asyncio
async def test_standalone_get_reaches_mock_transport_with_host_and_no_client_defaults() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Authorization": "Bearer injected-secret",
            "Cookie": "injected-cookie=value",
            "User-Agent": "injected-agent",
        },
    ) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        result = await adapter._get(DETAIL_URL, {"Accept": "application/json"})  # noqa: SLF001

    assert result.status_code == 200
    assert len(calls) == 1
    assert calls[0].headers["host"] == "vbpl-bientap-gateway.moj.gov.vn"
    assert calls[0].headers["accept"] == "application/json"
    assert "user-agent" not in calls[0].headers
    assert "authorization" not in calls[0].headers
    assert "cookie" not in calls[0].headers


@pytest.mark.asyncio
async def test_fetch_maps_metadata_dates_hash_and_exact_provenance() -> None:
    async with client(
        lambda request: (
            httpx.Response(200, json=payload())
            if str(request.url) == DETAIL_URL
            else httpx.Response(200, content=canonical_html())
        )
    ) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        snapshot = await adapter.fetch_document((await adapter.list_documents())[0])

    content = "<article>nội dung</article>"
    assert snapshot.title == "Luật mẫu"
    assert snapshot.document_type == "Luật"
    assert snapshot.issuing_authority == "Quốc hội"
    assert snapshot.issue_date == datetime(2025, 1, 1, tzinfo=UTC)
    assert snapshot.effective_date == datetime(2025, 2, 1, tzinfo=UTC)
    assert snapshot.source_updated_at == datetime(2025, 1, 3, tzinfo=UTC)
    assert snapshot.legal_status == "Còn hiệu lực"
    assert snapshot.content_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert snapshot.canonical_url == CANONICAL_URL
    assert snapshot.provenance.operation == "GET /qtdc/public/doc/175258 + canonical verification"
    assert snapshot.provenance.retrieved_at.tzinfo is not None
    assert snapshot.provenance.tls_verified is True


@pytest.mark.asyncio
async def test_fetch_maps_missing_optional_metadata_to_none_and_agency_status_fallbacks() -> None:
    minimal = payload(
        title=None,
        docType=None,
        organization=None,
        agencyName="Bộ Tư pháp",
        issueDate="not-a-date",
        effFrom=None,
        updatedDate=None,
        effStatus="Còn hiệu lực",
    )
    async with client(
        lambda request: (
            httpx.Response(200, json=minimal)
            if str(request.url) == DETAIL_URL
            else httpx.Response(200, content=canonical_html())
        )
    ) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        snapshot = await adapter.fetch_document((await adapter.list_documents())[0])

    assert snapshot.title is None
    assert snapshot.document_type is None
    assert snapshot.issuing_authority == "Bộ Tư pháp"
    assert snapshot.issue_date is snapshot.effective_date is snapshot.source_updated_at is None
    assert snapshot.legal_status == "Còn hiệu lực"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    [
        payload(id="other"),
        payload(docNum="other"),
        payload(documentContent={"content": "not html"}),
    ],
)
async def test_fetch_rejects_gateway_identity_number_and_content_mismatches(
    invalid: object,
) -> None:
    async with client(lambda _: httpx.Response(200, json=invalid)) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document((await adapter.list_documents())[0])

    assert raised.value.code in {
        SourceErrorCode.PROVENANCE_MISMATCH,
        SourceErrorCode.INVALID_RESPONSE,
    }


@pytest.mark.asyncio
async def test_fetch_rejects_a_canonical_mismatch() -> None:
    async with client(
        lambda request: (
            httpx.Response(200, json=payload())
            if str(request.url) == DETAIL_URL
            else httpx.Response(200, content=canonical_html("https://vbpl.vn/other"))
        )
    ) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document((await adapter.list_documents())[0])

    assert raised.value.code is SourceErrorCode.PROVENANCE_MISMATCH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(200, content=b"{"), httpx.Response(200, content=b"x" * 1025)],
)
async def test_fetch_rejects_invalid_or_oversized_gateway_json(response: httpx.Response) -> None:
    async with client(lambda _: response) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document((await adapter.list_documents())[0])

    assert raised.value.code is SourceErrorCode.INVALID_RESPONSE


@pytest.mark.asyncio
async def test_fetch_rejects_oversized_canonical_html() -> None:
    async with client(
        lambda request: (
            httpx.Response(200, json=payload())
            if str(request.url) == DETAIL_URL
            else httpx.Response(200, content=b"x" * 1025)
        )
    ) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document((await adapter.list_documents())[0])

    assert raised.value.code is SourceErrorCode.INVALID_RESPONSE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, SourceErrorCode.ACCESS_DENIED, False),
        (403, SourceErrorCode.ACCESS_DENIED, False),
        (404, SourceErrorCode.DOCUMENT_NOT_FOUND, False),
        (408, SourceErrorCode.TIMEOUT, True),
        (400, SourceErrorCode.INVALID_RESPONSE, False),
        (500, SourceErrorCode.UNAVAILABLE, True),
    ],
)
async def test_fetch_maps_statuses_without_retrying_unsafe_statuses(
    status: int, code: SourceErrorCode, retryable: bool
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    async with client(handler) as http_client:
        adapter = VBQPPLRestAdapter(settings(rest_max_attempts=1), source(), client=http_client)
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document((await adapter.list_documents())[0])

    assert (raised.value.code, raised.value.status_code, raised.value.retryable) == (
        code,
        status,
        retryable,
    )
    assert calls == 1


@pytest.mark.asyncio
async def test_fetch_retries_only_safe_statuses_with_numeric_and_http_date_retry_after() -> None:
    calls = 0
    sleeps: list[float] = []
    future = format_datetime(datetime.now(UTC) + timedelta(days=1), usegmt=True)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "9"})
        if calls == 2:
            return httpx.Response(503, headers={"Retry-After": future})
        if str(request.url) == DETAIL_URL:
            return httpx.Response(200, json=payload())
        return httpx.Response(200, content=canonical_html())

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    async with client(handler) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client, sleep=sleep)
        await adapter.fetch_document((await adapter.list_documents())[0])

    assert calls == 4
    assert sleeps == [2.0, 2.0]


@pytest.mark.asyncio
async def test_health_uses_only_the_exact_gateway_and_never_raises_remote_failures() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=payload())

    async with client(handler) as http_client:
        healthy = await VBQPPLRestAdapter(settings(), source(), client=http_client).health_check()
    assert healthy.status is SourceHealthStatus.HEALTHY
    assert [str(request.url) for request in calls] == [DETAIL_URL]

    async with client(lambda _: httpx.Response(503)) as http_client:
        unhealthy = await VBQPPLRestAdapter(
            settings(rest_max_attempts=1), source(), client=http_client
        ).health_check()
    assert unhealthy.status is SourceHealthStatus.UNHEALTHY
    assert unhealthy.error_code is SourceErrorCode.UNAVAILABLE


@pytest.mark.asyncio
async def test_owned_client_is_closed_but_injected_client_is_not() -> None:
    owned = VBQPPLRestAdapter(settings(), source())
    assert owned._client._trust_env is False  # noqa: SLF001
    assert owned._client.follow_redirects is False  # noqa: SLF001
    await owned.aclose()
    assert owned._client.is_closed  # noqa: SLF001

    async with client(lambda _: httpx.Response(200)) as injected:
        adapter = VBQPPLRestAdapter(settings(), source(), client=injected)
        await adapter.aclose()
        assert not injected.is_closed


@pytest.mark.asyncio
async def test_errors_and_logs_never_leak_remote_payloads(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    async with client(lambda _: httpx.Response(400, content=SENTINEL.encode())) as http_client:
        adapter = VBQPPLRestAdapter(settings(), source(), client=http_client)
        with pytest.raises(SourceError) as raised:
            await adapter.fetch_document((await adapter.list_documents())[0])

    rendered = "\n".join(record.getMessage() for record in caplog.records) + str(raised.value)
    assert SENTINEL not in rendered
