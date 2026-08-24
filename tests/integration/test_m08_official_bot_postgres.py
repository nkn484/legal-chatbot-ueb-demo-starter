"""Opt-in PostgreSQL evidence for the M08 Official Zalo Bot pivot."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tests.conftest import StubReadiness, app_client

from legal_chatbot.api.app import create_app
from legal_chatbot.channels.adapters.official_bot import OfficialZaloBotChannelPort
from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.errors import ChannelError
from legal_chatbot.channels.formatter import ChannelFormatter
from legal_chatbot.channels.models import (
    ChannelDeliveryReceipt,
    ChannelDeliveryReceiptStatus,
    ChannelKind,
    ChannelOutboundMessage,
    ChannelOutboundReservationStatus,
)
from legal_chatbot.channels.orm import ChannelConversationBinding, ChannelOutboundDelivery
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry
from legal_chatbot.channels.repository import (
    PostgresChannelBindingRepository,
    PostgresChannelOutboundRepository,
)
from legal_chatbot.channels.service import ChannelService
from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.models import ConversationExchangeStatus
from legal_chatbot.conversation.orm import ConversationExchange
from legal_chatbot.conversation.repository import PostgresConversationRepository
from legal_chatbot.conversation.service import ConversationService
from legal_chatbot.core.config import Settings
from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.models import ResolvedCitation, RetrievalDecision, RetrievalReason
from legal_chatbot.runtime.m08 import ChannelRuntime
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_ROOT = Path(__file__).resolve().parents[2]


async def _connect(url: URL, database: str) -> asyncpg.Connection:
    assert url.host and url.username and url.password
    return await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=database,
    )


async def _drop(admin: asyncpg.Connection, name: str) -> None:
    await admin.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        name,
    )
    await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


def _upgrade(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, "Alembic upgrade failed"


def _settings() -> ChannelSettings:
    return ChannelSettings(
        enabled=True,
        ZALO_OFFICIAL_BOT_TOKEN="m08-official-token-012345",
        ZALO_OFFICIAL_BOT_WEBHOOK_SECRET="m08-official-webhook-secret-012345",
        CHANNEL_IDENTITY_HMAC_KEY="m08-official-identity-key-012345678901",
    )


async def _database() -> tuple[
    asyncpg.Connection, str, AsyncEngine, async_sessionmaker[AsyncSession]
]:
    source = make_url(Settings().database_url.get_secret_value())
    name = f"m08_official_{uuid4().hex}"
    url = source.set(database=name).render_as_string(hide_password=False)
    admin = await _connect(source, "postgres")
    await _drop(admin, name)
    await admin.execute(f'CREATE DATABASE "{name}"')
    _upgrade(url)
    engine = create_async_engine(url, pool_pre_ping=True)
    return (
        admin,
        name,
        engine,
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )


async def _close_database(admin: asyncpg.Connection, name: str, engine: AsyncEngine) -> None:
    await engine.dispose()
    try:
        await _drop(admin, name)
    finally:
        await admin.close()


async def _seed_evidence(
    factory: async_sessionmaker[AsyncSession], now: datetime
) -> ResolvedCitation:
    run_id, document_id, version_id, provenance_id, chunk_id, citation_id = (
        uuid4() for _ in range(6)
    )
    digest = "a" * 64
    async with factory.begin() as session:
        session.add_all(
            (
                RetrievalRun(
                    id=run_id,
                    strategy="m08-official",
                    strategy_version="1",
                    scope="LATEST_INGESTED",
                    query_max_chars=1,
                    top_k=1,
                    candidate_count=1,
                    citation_count=1,
                    evidence_decision=RetrievalDecision.EVIDENCE_AVAILABLE.value,
                    evidence_reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE.value,
                    created_at=now,
                ),
                LegalDocument(
                    id=document_id, source_id="VBQPPL", external_id=f"m08-{document_id.hex}"
                ),
                DocumentVersion(
                    id=version_id,
                    document_id=document_id,
                    version_number=1,
                    raw_html="<p>official evidence</p>",
                    normalized_text="official evidence",
                    snapshot_sha256=digest,
                    source_content_sha256=digest,
                    normalized_text_sha256=digest,
                    normalizer_version="m08-official",
                    normalized_block_count=1,
                ),
                SourceProvenanceRecord(
                    id=provenance_id,
                    document_version_id=version_id,
                    provenance_type=ProvenanceType.SOURCE_FETCH.value,
                    source_id="VBQPPL",
                    transport="test",
                    operation="m08_official",
                    retrieved_at=now,
                    tls_verified=True,
                ),
                DocumentChunk(
                    id=chunk_id,
                    document_version_id=version_id,
                    ordinal=0,
                    content_text="official evidence",
                    start_char=0,
                    end_char=17,
                    content_sha256=digest,
                    chunker_version="m08-official",
                ),
                CitationRecord(
                    id=citation_id,
                    retrieval_run_id=run_id,
                    document_chunk_id=chunk_id,
                    source_provenance_record_id=provenance_id,
                    rank=1,
                    lexical_score=1.0,
                ),
            )
        )
    return ResolvedCitation(
        citation_id=citation_id,
        retrieval_run_id=run_id,
        document_chunk_id=chunk_id,
        document_version_id=version_id,
        document_id=document_id,
        source_provenance_record_id=provenance_id,
        source_id="VBQPPL",
        external_id="m08-official",
    )


@pytest.mark.asyncio
async def test_official_binding_and_outbound_repository_concurrency_and_reclaim() -> None:
    admin, name, engine, factory = await _database()
    now = datetime.now(UTC).replace(microsecond=0)
    settings = _settings()
    binding = PostgresChannelBindingRepository(factory, settings)
    outbound = PostgresChannelOutboundRepository(factory, settings)
    identity, delivery = "a" * 64, "b" * 64
    try:
        first, second = await asyncio.gather(
            binding.reserve(identity, now), binding.reserve(identity, now)
        )
        assert {first.status.value, second.status.value} == {"RESERVED", "PROCESSING"}
        reserved = first if first.status.value == "RESERVED" else second
        conversation = await PostgresConversationRepository(
            factory, ConversationSettings()
        ).create_conversation(now)
        active = await binding.activate(reserved, conversation.conversation_id, now)
        assert (await binding.reserve(identity, now)).status.value == "ACTIVE"

        orphan = await binding.reserve("c" * 64, now)
        orphan_conversation = await PostgresConversationRepository(
            factory, ConversationSettings()
        ).create_conversation(now)
        reclaimed = await binding.reserve("c" * 64, now + timedelta(seconds=121))
        assert reclaimed.status.value == "RESERVED"
        with pytest.raises(ChannelError):
            await binding.activate(
                orphan, orphan_conversation.conversation_id, now + timedelta(seconds=121)
            )

        exchange_id = uuid4()
        placeholder_run = uuid4()
        async with factory.begin() as session:
            session.add(
                RetrievalRun(
                    id=placeholder_run,
                    strategy="m08-placeholder",
                    strategy_version="1",
                    scope="LATEST_INGESTED",
                    query_max_chars=1,
                    top_k=1,
                    candidate_count=0,
                    citation_count=0,
                    evidence_decision=RetrievalDecision.NO_RESULTS.value,
                    evidence_reason=RetrievalReason.NO_LEXICAL_MATCH.value,
                )
            )
            await session.flush()
            session.add(
                ConversationExchange(
                    id=exchange_id,
                    conversation_id=conversation.conversation_id,
                    delivery_key_sha256="d" * 64,
                    ordinal=1,
                    status=ConversationExchangeStatus.COMPLETED.value,
                    user_text="test",
                    assistant_text="answer",
                    chat_outcome="CLARIFICATION",
                    chat_reason="NO_RESULTS",
                    retrieval_run_id=placeholder_run,
                    completed_at=now,
                )
            )
        message = ChannelOutboundMessage(
            identity_hmac=identity,
            delivery_hmac=delivery,
            exchange_id=exchange_id,
            text="answer",
            citation_count=0,
        )
        one, two = await asyncio.gather(
            outbound.reserve(active.binding_id, message, now),
            outbound.reserve(active.binding_id, message, now),
        )
        assert one.status is two.status is ChannelOutboundReservationStatus.RESERVED
        sent_one, sent_two = await asyncio.gather(
            outbound.mark_sending(one, now), outbound.mark_sending(two, now)
        )
        assert {sent_one.status, sent_two.status} == {
            ChannelOutboundReservationStatus.SENDING,
            ChannelOutboundReservationStatus.PROCESSING,
        }
        sending = (
            sent_one if sent_one.status is ChannelOutboundReservationStatus.SENDING else sent_two
        )
        completed = await outbound.complete(
            sending,
            ChannelDeliveryReceipt(status=ChannelDeliveryReceiptStatus.SENT, duration_ms=0),
            now,
        )
        assert completed.status is ChannelOutboundReservationStatus.SENT
        assert (
            await outbound.reserve(active.binding_id, message, now)
        ).status is ChannelOutboundReservationStatus.SENT
        timeout_exchange, mismatch_exchange = uuid4(), uuid4()
        async with factory.begin() as session:
            session.add_all(
                (
                    ConversationExchange(
                        id=timeout_exchange,
                        conversation_id=conversation.conversation_id,
                        delivery_key_sha256="e" * 64,
                        ordinal=2,
                        status=ConversationExchangeStatus.COMPLETED.value,
                        user_text="test",
                        assistant_text="answer",
                        chat_outcome="CLARIFICATION",
                        chat_reason="NO_RESULTS",
                        retrieval_run_id=placeholder_run,
                        completed_at=now,
                    ),
                    ConversationExchange(
                        id=mismatch_exchange,
                        conversation_id=conversation.conversation_id,
                        delivery_key_sha256="f" * 64,
                        ordinal=3,
                        status=ConversationExchangeStatus.COMPLETED.value,
                        user_text="test",
                        assistant_text="answer",
                        chat_outcome="CLARIFICATION",
                        chat_reason="NO_RESULTS",
                        retrieval_run_id=placeholder_run,
                        completed_at=now,
                    ),
                )
            )
        with pytest.raises(ChannelError):
            await outbound.reserve(
                active.binding_id,
                message.model_copy(update={"exchange_id": mismatch_exchange}),
                now,
            )
        timeout_message = message.model_copy(
            update={"delivery_hmac": "e" * 64, "exchange_id": timeout_exchange}
        )
        timeout_reserved = await outbound.reserve(active.binding_id, timeout_message, now)
        timeout_sending = await outbound.mark_sending(timeout_reserved, now)
        timeout_completed = await outbound.complete(
            timeout_sending,
            ChannelDeliveryReceipt(
                status=ChannelDeliveryReceiptStatus.TIMEOUT,
                safe_error_code="BOT_TIMEOUT",
                duration_ms=0,
            ),
            now,
        )
        assert timeout_completed.status is ChannelOutboundReservationStatus.UNKNOWN
        assert (
            await outbound.reserve(active.binding_id, timeout_message, now)
        ).status is ChannelOutboundReservationStatus.UNKNOWN
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(ChannelConversationBinding))
                == 2
            )
            assert (
                await session.scalar(select(ChannelConversationBinding.channel_kind).limit(1))
                == ChannelKind.ZALO_OFFICIAL_BOT.value
            )
            assert (
                await session.scalar(select(ChannelOutboundDelivery.channel_kind).limit(1))
                == ChannelKind.ZALO_OFFICIAL_BOT.value
            )
    finally:
        await _close_database(admin, name, engine)


class _CountingChat:
    def __init__(self, citation: ResolvedCitation) -> None:
        self.citation = citation
        self.calls = 0

    async def respond(self, _request: object) -> GroundedChatResult:
        self.calls += 1
        return GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer="Official grounded answer",
            retrieval_run_id=self.citation.retrieval_run_id,
            citations=(self.citation,),
            provider="fake",
            model="fake",
        )


class _ClosableProvider:
    async def aclose(self) -> None:
        return None


class _FailOnceOutbound:
    """Test-only completion fault retaining real durable reserve and mark operations."""

    def __init__(self, delegate: PostgresChannelOutboundRepository) -> None:
        self.delegate = delegate
        self.fail_next_complete = False
        self.complete_calls = 0
        self.reserve_error: Exception | None = None

    async def reserve(self, *args):
        try:
            return await self.delegate.reserve(*args)
        except Exception as error:
            self.reserve_error = error
            raise

    async def mark_sending(self, *args):
        return await self.delegate.mark_sending(*args)

    async def complete(self, *args):
        self.complete_calls += 1
        if self.fail_next_complete:
            self.fail_next_complete = False
            raise RuntimeError("test-only completion failure")
        return await self.delegate.complete(*args)


@pytest.mark.asyncio
async def test_official_webhook_replay_executes_one_chat_and_one_bot_send() -> None:
    admin, name, engine, factory = await _database()
    now = datetime.now(UTC).replace(microsecond=0)
    settings = _settings()
    sends: list[dict[str, object]] = []
    try:
        citation = await _seed_evidence(factory, now)
        resolver = PostgresCitationResolver(factory)
        chat = _CountingChat(citation)
        conversation = ConversationService(
            PostgresConversationRepository(factory, ConversationSettings()),
            chat,
            resolver,
            ConversationSettings(),
        )
        registry = OfficialBotRecipientRegistry()
        outbound = _FailOnceOutbound(PostgresChannelOutboundRepository(factory, settings))

        async def send(request: httpx.Request) -> httpx.Response:
            assert (
                str(request.url)
                == "https://bot-api.zaloplatforms.com/botm08-official-token-012345/sendMessage"
            )
            sends.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

        client = httpx.AsyncClient(transport=httpx.MockTransport(send))
        channel = OfficialZaloBotChannelPort(settings, registry, client=client)
        assert ChannelFormatter(settings).format(await chat.respond(object())).text
        chat.calls = 0
        service = ChannelService(
            PostgresChannelBindingRepository(factory, settings),
            outbound,
            conversation,
            channel,
            ChannelFormatter(settings),
            settings,
        )
        runtime = ChannelRuntime(
            ingress=service, provider=_ClosableProvider(), channel=channel, recipients=registry
        )

        async def runtime_factory(_engine: AsyncEngine) -> ChannelRuntime:
            return runtime

        application = create_app(
            settings=Settings(DATABASE_URL=engine.url.render_as_string(hide_password=False)),
            engine=engine,
            readiness=StubReadiness(),
            channel_settings=settings,
            channel_runtime_factory=runtime_factory,
        )
        envelope = {
            "ok": True,
            "result": {
                "event_name": "message.text.received",
                "message": {
                    "chat": {"id": 12345, "chat_type": "PRIVATE"},
                    "from": {"id": 67890, "is_bot": False},
                    "message_id": 44,
                    "text": "private input",
                    "date": int(now.timestamp() * 1000),
                },
            },
        }
        headers = {
            "Content-Type": "application/json",
            "X-Bot-Api-Secret-Token": "m08-official-webhook-secret-012345",
        }
        async with app_client(application) as client_api:
            first = await client_api.post("/webhooks/zalo-bot", json=envelope, headers=headers)
            replay = await client_api.post("/webhooks/zalo-bot", json=envelope, headers=headers)
            failing = json.loads(json.dumps(envelope))
            failing["result"]["message"]["message_id"] = 45
            outbound.fail_next_complete = True
            first_failure = await client_api.post(
                "/webhooks/zalo-bot", json=failing, headers=headers
            )
            replay_failure = await client_api.post(
                "/webhooks/zalo-bot", json=failing, headers=headers
            )
        await client.aclose()

        assert first.status_code == replay.status_code == 200, repr(outbound.reserve_error)
        assert first_failure.status_code == 503 and replay_failure.status_code == 200
        assert chat.calls == 2 and len(sends) == 2 and outbound.complete_calls == 2
        assert set(sends[0]) == {"chat_id", "text"} and sends[0]["chat_id"] == 12345
        async with factory() as session:
            assert (
                await session.scalar(select(func.count()).select_from(ChannelConversationBinding))
                == 1
            )
            assert await session.scalar(select(func.count()).select_from(ConversationExchange)) == 2
            assert (
                await session.scalar(select(func.count()).select_from(ChannelOutboundDelivery)) == 2
            )
            assert set((await session.scalars(select(ChannelOutboundDelivery.status))).all()) == {
                "SENT",
                "SENDING",
            }
    finally:
        await _close_database(admin, name, engine)
