"""Focused official Zalo Bot channel contracts and HTTP boundary tests."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from tests.conftest import StubReadiness, app_client

from legal_chatbot.api.app import create_app
from legal_chatbot.channels.adapters.official_bot import OfficialZaloBotChannelPort
from legal_chatbot.channels.auth import BOT_SECRET_HEADER, delivery_hmac, identity_hmac
from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.formatter import OVERFLOW_REPLY_TEXT, ChannelFormatter
from legal_chatbot.channels.models import (
    ChannelDeliveryReceiptStatus,
    ChannelInboundMessage,
    ChannelIngressReceipt,
    ChannelIngressStatus,
    ChannelOutboundMessage,
)
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry
from legal_chatbot.channels.webhook import install_official_bot_webhook
from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.core.config import Settings
from legal_chatbot.retrieval.models import ResolvedCitation
from legal_chatbot.runtime.m08 import ChannelRuntime, build_m08_runtime


def _settings(*, enabled: bool = True) -> ChannelSettings:
    return ChannelSettings(
        enabled=enabled,
        ZALO_OFFICIAL_BOT_TOKEN="token-value-012345",
        ZALO_OFFICIAL_BOT_WEBHOOK_SECRET="webhook-secret-012345",
        CHANNEL_IDENTITY_HMAC_KEY="identity-key-012345678901234567890123",
    )


def test_identity_and_delivery_are_domain_separated_and_opaque() -> None:
    key = SecretStr("identity-key-012345678901234567890123")
    identity = identity_hmac(key, 12, 34)
    delivery = delivery_hmac(key, 12, 34, 56)

    assert len(identity) == len(delivery) == 64
    assert identity != delivery
    assert "12" not in identity and "34" not in delivery


def test_inbound_and_outbound_contracts_accept_deliberate_lf_newlines() -> None:
    inbound = ChannelInboundMessage(
        identity_hmac="a" * 64,
        delivery_hmac="b" * 64,
        text="  first\nsecond  ",
        received_at="2026-08-20T00:00:00Z",
    )
    outbound = ChannelOutboundMessage(
        identity_hmac="a" * 64,
        delivery_hmac="b" * 64,
        exchange_id=uuid4(),
        text="  first\nsecond  ",
        citation_count=0,
    )

    assert inbound.text == outbound.text == "first\nsecond"


@pytest.mark.parametrize("forbidden", ("first\rsecond", "first\tsecond", "first\x00second"))
def test_channel_text_contracts_reject_non_lf_controls(forbidden: str) -> None:
    with pytest.raises(ValueError):
        ChannelInboundMessage(
            identity_hmac="a" * 64,
            delivery_hmac="b" * 64,
            text=forbidden,
            received_at="2026-08-20T00:00:00Z",
        )
    with pytest.raises(ValueError):
        ChannelOutboundMessage(
            identity_hmac="a" * 64,
            delivery_hmac="b" * 64,
            exchange_id=uuid4(),
            text=forbidden,
            citation_count=0,
        )


def test_formatter_citations_construct_a_newline_safe_outbound_contract() -> None:
    run_id = uuid4()
    citation = ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=run_id,
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="official-test",
        title="Official source",
    )
    formatted = ChannelFormatter(_settings()).format(
        GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer="Grounded answer",
            retrieval_run_id=run_id,
            citations=(citation,),
            provider="test-provider",
            model="test-model",
        )
    )
    outbound = ChannelOutboundMessage(
        identity_hmac="a" * 64,
        delivery_hmac="b" * 64,
        exchange_id=uuid4(),
        text=formatted.text,
        citation_count=formatted.citation_count,
    )

    assert "\n" in outbound.text


def test_formatter_keeps_neutral_citation_labels_and_verbatim_title() -> None:
    citation = ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="official-test",
        document_number="12/2026/QĐ-TTg",
        title="Quy định “Tôi” và thầy/cô trong tiêu đề gốc",
    )

    rendered = ChannelFormatter._format_citation(citation)

    assert rendered == (
        "Nguồn: VBQPPL; Số văn bản: 12/2026/QĐ-TTg; "
        "Tiêu đề: Quy định “Tôi” và thầy/cô trong tiêu đề gốc"
    )


def test_overflow_text_uses_the_approved_vietnamese_bot_voice() -> None:
    assert OVERFLOW_REPLY_TEXT.startswith("Dạ,")
    assert "em" in OVERFLOW_REPLY_TEXT
    assert "Thầy/cô" in OVERFLOW_REPLY_TEXT


@pytest.mark.asyncio
@pytest.mark.parametrize("message_id", ("m", 1))
async def test_official_adapter_uses_fixed_endpoint_and_exact_body(message_id: str | int) -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})

    registry = OfficialBotRecipientRegistry()
    identity = "a" * 64
    registry.remember(identity, 123)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OfficialZaloBotChannelPort(_settings(), registry, client=client)
        receipt = await adapter.send(
            ChannelOutboundMessage(
                identity_hmac=identity,
                delivery_hmac="b" * 64,
                exchange_id="12345678-1234-5678-1234-567812345678",
                text="Xin chào",
                citation_count=0,
            )
        )

    assert receipt.status is ChannelDeliveryReceiptStatus.SENT
    assert seen == {
        "url": "https://bot-api.zaloplatforms.com/bottoken-value-012345/sendMessage",
        "body": b'{"chat_id":123,"text":"Xin ch\xc3\xa0o"}',
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    (
        {"ok": True, "result": {"message_id": True}},
        {"ok": True, "result": {"message_id": False}},
        {"ok": True, "result": {"message_id": None}},
        {"ok": True, "result": {"message_id": []}},
        {"ok": True, "result": {"message_id": {}}},
        {"ok": True, "result": {"message_id": 1.5}},
        {"ok": True, "result": None},
        {"ok": True, "result": []},
        {"ok": True, "result": {}},
        {"ok": True},
    ),
)
async def test_official_adapter_rejects_malformed_success_response_once(payload: object) -> None:
    attempts = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, json=payload)

    registry = OfficialBotRecipientRegistry()
    identity = "a" * 64
    registry.remember(identity, 123)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = OfficialZaloBotChannelPort(_settings(), registry, client=client)
        receipt = await adapter.send(
            ChannelOutboundMessage(
                identity_hmac=identity,
                delivery_hmac="b" * 64,
                exchange_id="12345678-1234-5678-1234-567812345678",
                text="Xin chào",
                citation_count=0,
            )
        )

    assert receipt.status is ChannelDeliveryReceiptStatus.INVALID_RESPONSE
    assert receipt.safe_error_code == "BOT_INVALID_RESPONSE"
    assert attempts == 1


def test_channel_settings_read_documented_resource_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("CHANNEL_MAX_BODY_BYTES", "1024")
    monkeypatch.setenv("CHANNEL_MAX_OUTBOUND_CHARS", "100")
    monkeypatch.setenv("CHANNEL_OUTBOUND_MAX_ATTEMPTS", "1")
    monkeypatch.setenv("CHANNEL_BINDING_LEASE_SECONDS", "60")
    monkeypatch.setenv("CHANNEL_TIMEOUT_SECONDS", "5.5")

    settings = ChannelSettings()

    assert settings.max_body_bytes == 1024
    assert settings.max_outbound_chars == 100
    assert settings.outbound_max_attempts == 1
    assert settings.binding_lease_seconds == 60
    assert settings.timeout_seconds == 5.5


def test_channel_settings_keep_documented_resource_environment_bounds(monkeypatch) -> None:
    monkeypatch.setenv("CHANNEL_OUTBOUND_MAX_ATTEMPTS", "2")

    with pytest.raises(ValueError):
        ChannelSettings()


@pytest.mark.asyncio
async def test_webhook_ignores_group_event_without_calling_service() -> None:
    calls = 0

    class Ingress:
        async def handle_inbound(self, _message, _now):
            nonlocal calls
            calls += 1
            return ChannelIngressReceipt(status=ChannelIngressStatus.ACKNOWLEDGED)

    app = create_app(
        settings=Settings(DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/demo"),
        engine=object(),
        readiness=StubReadiness(),
        channel_settings=_settings(),
        channel_ingress=Ingress(),
    )
    body = (
        b'{"event_name":"message.text.received","message":{"chat":{"id":1,'
        b'"chat_type":"GROUP"},"from":{"id":2,"is_bot":false},"message_id":3}}'
    )
    async with app_client(app) as client:
        response = await client.post(
            "/webhooks/zalo-bot",
            content=body,
            headers={
                "Content-Type": "application/json",
                BOT_SECRET_HEADER: "webhook-secret-012345",
            },
        )

    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}'
    assert calls == 0


@pytest.mark.asyncio
async def test_documented_and_m00_webhook_envelopes_normalize_identically() -> None:
    received = []
    registry = OfficialBotRecipientRegistry()

    class Ingress:
        async def handle_inbound(self, message, now):
            received.append((message, now))
            return ChannelIngressReceipt(status=ChannelIngressStatus.ACKNOWLEDGED)

    app = FastAPI()
    install_official_bot_webhook(app, Ingress(), _settings(), registry)
    message = {
        "chat": {"id": 1001, "chat_type": "PRIVATE", "ignored": "field"},
        "from": {"id": 2002, "is_bot": False},
        "message_id": 3003,
        "text": "  Xin chào  ",
        "date": 1_725_000_000_000,
    }
    top_level = {"event_name": "message.text.received", "message": message, "extra": True}
    documented = {
        "ok": True,
        "result": {"event_name": "message.text.received", "message": message, "other": None},
    }
    headers = {"Content-Type": "application/json", BOT_SECRET_HEADER: "webhook-secret-012345"}
    async with app_client(app) as client:
        assert (
            await client.post("/webhooks/zalo-bot", json=top_level, headers=headers)
        ).status_code == 200
        assert (
            await client.post("/webhooks/zalo-bot", json=documented, headers=headers)
        ).status_code == 200

    assert len(received) == 2
    assert received[0][0].identity_hmac == received[1][0].identity_hmac
    assert received[0][0].delivery_hmac == received[1][0].delivery_hmac
    assert received[0][0].text == "Xin chào"
    assert registry.resolve(received[0][0].identity_hmac) == 1001


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "event_name,message",
    [
        ("message.unsupported.received", {"private": "ignored"}),
        (
            "message.text.received",
            {"chat": {"id": 1, "chat_type": "PRIVATE"}, "from": {"id": 2, "is_bot": True}},
        ),
        (
            "message.text.received",
            {
                "chat": {"id": 1, "chat_type": "PRIVATE"},
                "from": {"id": 2, "is_bot": False},
                "message_id": 3,
            },
        ),
    ],
)
async def test_webhook_ignores_unsupported_bot_and_non_text_events(event_name, message) -> None:
    calls = 0

    class Ingress:
        async def handle_inbound(self, _message, _now):
            nonlocal calls
            calls += 1
            return ChannelIngressReceipt(status=ChannelIngressStatus.ACKNOWLEDGED)

    app = FastAPI()
    install_official_bot_webhook(app, Ingress(), _settings(), OfficialBotRecipientRegistry())
    async with app_client(app) as client:
        response = await client.post(
            "/webhooks/zalo-bot",
            json={"event_name": event_name, "message": message},
            headers={
                "Content-Type": "application/json",
                BOT_SECRET_HEADER: "webhook-secret-012345",
            },
        )

    assert response.status_code == 200
    assert calls == 0


@pytest.mark.asyncio
async def test_webhook_returns_400_for_missing_required_fields_in_text_event() -> None:
    app = FastAPI()
    install_official_bot_webhook(app, object(), _settings(), OfficialBotRecipientRegistry())  # type: ignore[arg-type]
    async with app_client(app) as client:
        response = await client.post(
            "/webhooks/zalo-bot",
            json={"event_name": "message.text.received", "message": {"chat": {}}},
            headers={
                "Content-Type": "application/json",
                BOT_SECRET_HEADER: "webhook-secret-012345",
            },
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_webhook_rejects_bad_secret_before_json() -> None:
    app = create_app(
        settings=Settings(DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/demo"),
        engine=object(),
        readiness=StubReadiness(),
        channel_settings=_settings(),
        channel_ingress=object(),  # type: ignore[arg-type]
    )
    async with app_client(app) as client:
        response = await client.post(
            "/webhooks/zalo-bot",
            content=b'{"private":"untrusted"}',
            headers={"Content-Type": "application/json", BOT_SECRET_HEADER: "wrong"},
        )

    assert response.status_code == 401


def test_registry_is_bounded_and_clearable() -> None:
    registry = OfficialBotRecipientRegistry(maximum=1)
    registry.remember("a" * 64, 1)
    registry.remember("b" * 64, 2)
    assert registry.resolve("a" * 64) is None
    assert registry.resolve("b" * 64) == 2
    registry.clear()
    assert registry.resolve("b" * 64) is None


@pytest.mark.asyncio
async def test_runtime_disabled_constructs_no_provider_and_closes_registry_before_resources() -> (
    None
):
    calls: list[str] = []

    class Resource:
        async def aclose(self) -> None:
            calls.append("close")

    registry = OfficialBotRecipientRegistry()
    registry.remember("a" * 64, 1)
    runtime = ChannelRuntime(
        ingress=object(),  # type: ignore[arg-type]
        provider=Resource(),  # type: ignore[arg-type]
        channel=Resource(),  # type: ignore[arg-type]
        recipients=registry,
    )
    await runtime.aclose()
    await runtime.aclose()
    assert registry.resolve("a" * 64) is None
    assert calls == ["close", "close"]

    disabled = await build_m08_runtime(
        object(),
        _settings(enabled=False),
        provider_factory=lambda _settings: (_ for _ in ()).throw(AssertionError),  # type: ignore[arg-type]
    )
    assert disabled is None
