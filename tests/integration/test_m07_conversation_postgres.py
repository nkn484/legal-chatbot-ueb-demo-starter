"""Opt-in real M05/M06/M07 multi-turn vertical coverage with a fake provider."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from legal_chatbot.chat.config import ChatSettings
from legal_chatbot.chat.models import ChatRequest
from legal_chatbot.chat.parser import StrictProviderJsonParser
from legal_chatbot.chat.service import GroundedChatService
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import ConversationExchangeStatus, ConversationRequest
from legal_chatbot.conversation.orm import (
    Conversation,
    ConversationExchange,
    ConversationExchangeReference,
)
from legal_chatbot.conversation.policy import build_chat_request, delivery_key_sha256
from legal_chatbot.conversation.repository import PostgresConversationRepository
from legal_chatbot.conversation.service import ConversationService
from legal_chatbot.core.config import Settings
from legal_chatbot.core.logging import JsonFormatter
from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.grounding_evidence import PostgresGroundingEvidenceAdapter
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.models import (
    GenerationRequest,
    GenerationResult,
    ProviderHealth,
    ProviderHealthStatus,
)
from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    TemporalScope,
)
from legal_chatbot.retrieval.service import RetrievalService
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ID = "TESTM07VERTICAL"


async def _connect(url: URL, database: str) -> asyncpg.Connection:
    if url.host is None or url.username is None or url.password is None:
        raise RuntimeError("DATABASE_URL must include host, user, and password")
    return await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=database,
    )


async def _drop_database(connection: asyncpg.Connection, database: str) -> None:
    await connection.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        database,
    )
    await connection.execute(f'DROP DATABASE IF EXISTS "{database}"')


def _upgrade(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, "Alembic setup command failed"


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.failure: Exception | None = None

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return GenerationResult(
            text='{"answer":"Grounded vertical answer VERTICAL_PROVIDER_OUTPUT_SENTINEL."}',
            provider="m07-fake",
            model="m07-fake-model",
            request_id=f"m07-request-{self.calls}",
            duration_ms=0,
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderHealthStatus.HEALTHY,
            provider="m07-fake",
            model="m07-fake-model",
            duration_ms=0,
        )

    async def aclose(self) -> None:
        return None


class _TrackingRetrieval:
    def __init__(self, service: RetrievalService) -> None:
        self._service = service
        self.calls = 0
        self.requests: list[RetrievalRequest] = []

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self.calls += 1
        self.requests.append(request)
        return await self._service.retrieve(request)


class _TrackingChat:
    def __init__(self, service: GroundedChatService) -> None:
        self._service = service
        self.calls = 0
        self.requests: list[ChatRequest] = []

    async def respond(self, request: ChatRequest):
        self.calls += 1
        self.requests.append(request)
        return await self._service.respond(request)


class _TrackingResolver:
    def __init__(self, resolver: PostgresCitationResolver) -> None:
        self._resolver = resolver
        self.calls: list[tuple[UUID, UUID]] = []

    async def resolve(self, citation_id: UUID, expected_retrieval_run_id: UUID) -> ResolvedCitation:
        self.calls.append((citation_id, expected_retrieval_run_id))
        return await self._resolver.resolve(citation_id, expected_retrieval_run_id)


def _provider_settings() -> ProviderSettings:
    return ProviderSettings.model_validate(
        {
            "LLM_BASE_URL": "https://provider.example.test/v1",
            "LLM_MODEL": "m07-fake-model",
            "LLM_API_KEY": "m07-test-key",
            "LLM_MAX_INPUT_CHARS": 20_000,
            "LLM_MAX_OUTPUT_TOKENS": 512,
        }
    )


async def _seed_document(factory: async_sessionmaker[AsyncSession], now: datetime) -> UUID:
    document_id = uuid4()
    version_id = uuid4()
    provenance_id = uuid4()
    digest = "a" * 64
    async with factory() as session:
        async with session.begin():
            session.add_all(
                (
                    LegalDocument(
                        id=document_id,
                        source_id=_SOURCE_ID,
                        external_id=f"vertical-{document_id.hex}",
                    ),
                    DocumentVersion(
                        id=version_id,
                        document_id=document_id,
                        version_number=1,
                        raw_html="<p>vertical evidence</p>",
                        normalized_text=(
                            "verticalfirst verticalsecond verticalcompaction active topic "
                            "VERTICAL_EXCERPT_SENTINEL VERTICAL_QUESTION_SENTINEL "
                            "VERTICAL_SECOND_SENTINEL"
                        ),
                        snapshot_sha256=digest,
                        source_content_sha256=digest,
                        normalized_text_sha256=digest,
                        normalizer_version="m07-vertical",
                        normalized_block_count=1,
                    ),
                    SourceProvenanceRecord(
                        id=provenance_id,
                        document_version_id=version_id,
                        provenance_type=ProvenanceType.SOURCE_FETCH.value,
                        source_id=_SOURCE_ID,
                        transport="test",
                        operation="m07_vertical",
                        retrieved_at=now,
                        tls_verified=True,
                    ),
                    DocumentChunk(
                        id=uuid4(),
                        document_version_id=version_id,
                        ordinal=0,
                        content_text=(
                            "verticalfirst verticalsecond verticalcompaction active topic "
                            "VERTICAL_EXCERPT_SENTINEL VERTICAL_QUESTION_SENTINEL "
                            "VERTICAL_SECOND_SENTINEL"
                        ),
                        start_char=0,
                        end_char=73,
                        content_sha256=digest,
                        chunker_version="m07-vertical",
                    ),
                )
            )
    return document_id


@pytest.mark.asyncio
async def test_m07_real_multi_turn_vertical_slice(caplog: pytest.LogCaptureFixture) -> None:
    source_url = make_url(Settings().database_url.get_secret_value())
    database = f"m07_vertical_{uuid4().hex}"
    database_url = source_url.set(database=database).render_as_string(hide_password=False)
    admin = await _connect(source_url, "postgres")
    engine = None
    try:
        await _drop_database(admin, database)
        await admin.execute(f'CREATE DATABASE "{database}"')
        _upgrade(database_url)
        engine = create_async_engine(database_url, pool_pre_ping=True)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        now = datetime.now(UTC).replace(microsecond=0)
        document_id = await _seed_document(factory, now)

        conversation_repository = PostgresConversationRepository(factory, ConversationSettings())
        retrieval = _TrackingRetrieval(
            RetrievalService(PostgresLexicalRetrievalRepository(factory, (_SOURCE_ID,)))
        )
        provider = _CountingProvider()
        chat_settings = ChatSettings(max_citations=1, total_evidence_max_chars=2_000)
        resolver = _TrackingResolver(PostgresCitationResolver(factory))
        grounded = _TrackingChat(
            GroundedChatService(
                retrieval,
                PostgresGroundingEvidenceAdapter(factory, chat_settings),
                resolver,
                provider,
                StrictProviderJsonParser(),
                chat_settings,
                _provider_settings(),
            )
        )
        service = ConversationService(
            conversation_repository, grounded, resolver, ConversationSettings()
        )
        caplog.set_level(logging.INFO, logger="legal_chatbot")

        conversation = await service.create_conversation(now)
        first_text = "verticalfirst VERTICAL_QUESTION_SENTINEL"
        first = await service.respond(
            ConversationRequest(
                conversation_id=conversation.conversation_id, delivery_id="first", text=first_text
            ),
            now,
        )
        assert first.status.value == "COMPLETED"
        assert first.chat is not None and first.chat.citations
        assert provider.calls == 1
        async with factory() as session:
            assert (
                await session.scalar(
                    select(Conversation.state_version).where(
                        Conversation.id == conversation.conversation_id
                    )
                )
                == 1
            )

        second_text = "verticalsecond VERTICAL_SECOND_SENTINEL"
        second = await service.respond(
            ConversationRequest(
                conversation_id=conversation.conversation_id, delivery_id="second", text=second_text
            ),
            now,
        )
        assert second.status.value == "COMPLETED"
        assert provider.calls == 2
        assert grounded.requests[-1].question == second_text
        assert grounded.requests[-1].retrieval_query is not None
        assert first_text in grounded.requests[-1].retrieval_query
        assert grounded.requests[-1].conversation_context is not None
        assert second_text not in " ".join(
            turn.text for turn in grounded.requests[-1].conversation_context.recent_turns
        )
        assert await conversation_repository.load_snapshot(conversation.conversation_id, now)

        resolver_before_replay = len(resolver.calls)
        replay = await service.respond(
            ConversationRequest(
                conversation_id=conversation.conversation_id, delivery_id="first", text=first_text
            ),
            now,
        )
        assert replay.duplicate and replay.chat is not None
        assert provider.calls == 2
        assert len(resolver.calls) == resolver_before_replay + len(first.chat.citations)
        assert tuple(c.citation_id for c in replay.chat.citations) == tuple(
            c.citation_id for c in first.chat.citations
        )

        no_hit = await service.create_conversation(now)
        no_hit_result = await service.respond(
            ConversationRequest(
                conversation_id=no_hit.conversation_id, delivery_id="none", text="verticalnohit"
            ),
            now,
        )
        assert (
            no_hit_result.chat is not None and no_hit_result.chat.outcome.value == "CLARIFICATION"
        )
        assert provider.calls == 2

        temporal = await service.create_conversation(now)
        temporal_result = await service.respond(
            ConversationRequest(
                conversation_id=temporal.conversation_id,
                delivery_id="temporal",
                text="verticalfirst",
                temporal_scope=TemporalScope.AS_OF,
            ),
            now,
        )
        assert temporal_result.chat is not None
        assert temporal_result.chat.outcome.value == "REFUSAL"
        assert temporal_result.chat.reason.value == "UNSUPPORTED_TEMPORAL_SCOPE"
        assert provider.calls == 2
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ConversationExchangeReference)
                    .where(ConversationExchangeReference.exchange_id == temporal_result.exchange_id)
                )
                == 0
            )

        pending = await service.create_conversation(now)
        pending_request = ConversationRequest(
            conversation_id=pending.conversation_id,
            delivery_id="pending",
            text="verticalfirst",
        )
        pending_reservation = await conversation_repository.reserve(pending_request, now)
        assert pending_reservation.reservation is not None
        processing = await service.respond(pending_request, now)
        assert processing.status is ConversationExchangeStatus.PROCESSING
        assert processing.exchange_id == pending_reservation.reservation.exchange_id
        with pytest.raises(ConversationError) as busy:
            await service.respond(
                ConversationRequest(
                    conversation_id=pending.conversation_id,
                    delivery_id="pending-other",
                    text="verticalfirst",
                ),
                now,
            )
        assert busy.value.code is ConversationErrorCode.BUSY
        assert provider.calls == 2
        lease_later = now + timedelta(seconds=ConversationSettings().processing_lease_seconds + 1)
        with pytest.raises(ConversationError) as expired:
            await service.respond(pending_request, lease_later)
        assert expired.value.code is ConversationErrorCode.LEASE_EXPIRED
        assert (
            await conversation_repository.reserve(
                ConversationRequest(
                    conversation_id=pending.conversation_id,
                    delivery_id="pending-fresh",
                    text="verticalfirst",
                ),
                lease_later,
            )
        ).reservation is not None

        provider_failure = await service.create_conversation(now)
        provider.failure = RuntimeError("VERTICAL_PROVIDER_EXCEPTION_SENTINEL")
        failure_result = await service.respond(
            ConversationRequest(
                conversation_id=provider_failure.conversation_id,
                delivery_id="provider-failure",
                text="verticalfirst",
            ),
            now,
        )
        provider.failure = None
        assert failure_result.chat is not None
        assert failure_result.chat.outcome.value == "REFUSAL"
        assert failure_result.chat.reason.value == "PROVIDER_FAILURE"
        async with factory() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ConversationExchangeReference)
                    .where(ConversationExchangeReference.exchange_id == failure_result.exchange_id)
                )
                == 0
            )

        no_results_run_id = uuid4()
        compaction = await service.create_conversation(now)
        oldest_id = uuid4()
        async with factory() as session:
            async with session.begin():
                session.add(
                    RetrievalRun(
                        id=no_results_run_id,
                        strategy="m07-vertical",
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
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == compaction.conversation_id)
                    .values(
                        state_version=7,
                        rolling_summary="VERTICAL_SUMMARY_SENTINEL",
                        active_topic="verticalcompaction",
                    )
                )
                first_citation = first.chat.citations[0] if first.chat is not None else None
                session.add_all(
                    ConversationExchange(
                        id=oldest_id if ordinal == 1 else uuid4(),
                        conversation_id=compaction.conversation_id,
                        delivery_key_sha256=f"{ordinal:064x}",
                        ordinal=ordinal,
                        status=ConversationExchangeStatus.COMPLETED.value,
                        user_text=f"old question {ordinal}",
                        assistant_text=f"old answer {ordinal}",
                        chat_outcome="CLARIFICATION",
                        chat_reason="NO_RESULTS",
                        retrieval_run_id=no_results_run_id,
                        provider=None,
                        model=None,
                        completed_at=now,
                    )
                    for ordinal in range(1, 33)
                )
                await session.flush()
                if first_citation is not None:
                    session.add_all(
                        (
                            ConversationExchangeReference(
                                exchange_id=oldest_id,
                                kind="CITATION",
                                reference_id=first_citation.citation_id,
                                ordinal=0,
                            ),
                            ConversationExchangeReference(
                                exchange_id=oldest_id,
                                kind="DOCUMENT",
                                reference_id=first_citation.document_id,
                                ordinal=0,
                            ),
                        )
                    )
        compaction_request = ConversationRequest(
            conversation_id=compaction.conversation_id,
            delivery_id="compact",
            text="verticalcompaction",
        )
        compaction_result = await service.respond(compaction_request, now)
        assert compaction_result.chat is not None and compaction_result.chat.citations
        async with factory() as session:
            summary = await session.scalar(
                select(Conversation.rolling_summary).where(
                    Conversation.id == compaction.conversation_id
                )
            )
            assert (
                summary is not None and "status=COMPLETED" in summary and "citations=1" in summary
            )
            assert (
                await session.scalar(
                    select(ConversationExchange.id).where(ConversationExchange.id == oldest_id)
                )
                is None
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ConversationExchange)
                    .where(
                        ConversationExchange.conversation_id == compaction.conversation_id,
                        ConversationExchange.status.in_(("COMPLETED", "FAILED", "ABANDONED")),
                    )
                )
                == 32
            )
            assert (
                await session.scalar(
                    select(CitationRecord.id).where(
                        CitationRecord.id == first.chat.citations[0].citation_id
                    )
                )
                == first.chat.citations[0].citation_id
            )
        next_reservation = await conversation_repository.reserve(
            ConversationRequest(
                conversation_id=compaction.conversation_id,
                delivery_id="compact-next",
                text="verticalcompaction",
            ),
            now,
        )
        assert next_reservation.reservation is not None
        next_context = build_chat_request(
            ConversationRequest(
                conversation_id=compaction.conversation_id,
                delivery_id="compact-next",
                text="verticalcompaction",
            ),
            next_reservation.reservation,
            ConversationSettings(),
        ).conversation_context
        assert next_context is not None and next_context.rolling_summary is not None
        assert "status=COMPLETED" in next_context.rolling_summary

        async with factory() as session:
            async with session.begin():
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation.conversation_id)
                    .values(
                        created_at=now - timedelta(seconds=2), expires_at=now - timedelta(seconds=1)
                    )
                )
        assert await conversation_repository.purge_expired(now, 1) == 1
        async with factory() as session:
            assert (
                await session.scalar(
                    select(Conversation.id).where(Conversation.id == conversation.conversation_id)
                )
                is None
            )
            assert first.chat is not None
            assert (
                await session.scalar(
                    select(CitationRecord.id).where(
                        CitationRecord.id == first.chat.citations[0].citation_id
                    )
                )
                == first.chat.citations[0].citation_id
            )
            columns = set(
                (
                    await session.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_schema = 'public' "
                            "AND table_name = 'conversation_exchanges'"
                        )
                    )
                ).all()
            )
            assert "delivery_id" not in columns and "delivery_key_sha256" in columns
            m07_tables = set(
                (
                    await session.scalars(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public' "
                            "AND table_name IN ('conversations', 'conversation_exchanges', "
                            "'conversation_exchange_references')"
                        )
                    )
                ).all()
            )
            assert m07_tables == {
                "conversations",
                "conversation_exchanges",
                "conversation_exchange_references",
            }
            m05_columns = set(
                (
                    await session.scalars(
                        text(
                            "SELECT table_name || '.' || column_name "
                            "FROM information_schema.columns WHERE table_schema = 'public' "
                            "AND table_name IN ('retrieval_runs', 'citation_records')"
                        )
                    )
                ).all()
            )
            prohibited_m05 = {
                "question",
                "question_hash",
                "user_text",
                "assistant_text",
                "summary",
                "topic",
                "context",
                "retrieval_query",
                "prompt",
                "provider_body",
                "provider_output",
                "model_response",
            }
            assert not {
                column.rsplit(".", maxsplit=1)[1]
                for column in m05_columns
                if column.rsplit(".", maxsplit=1)[1] in prohibited_m05
            }

        async with factory() as session:
            assert (
                await session.scalar(
                    select(LegalDocument.id).where(LegalDocument.id == document_id)
                )
                == document_id
            )
            assert (
                await session.scalar(
                    select(ConversationExchange.id).where(
                        ConversationExchange.id == first.exchange_id
                    )
                )
                is None
            )
        log_payload = "\n".join(
            json.dumps(record.__dict__, default=str, ensure_ascii=False)
            + JsonFormatter().format(record)
            for record in caplog.records
        )
        sensitive_values = {
            first_text,
            second_text,
            "VERTICAL_EXCERPT_SENTINEL",
            "VERTICAL_SUMMARY_SENTINEL",
            "VERTICAL_PROVIDER_OUTPUT_SENTINEL",
            "VERTICAL_PROVIDER_EXCEPTION_SENTINEL",
            str(conversation.conversation_id),
            str(first.exchange_id),
            str(second.exchange_id),
            delivery_key_sha256("first"),
            delivery_key_sha256("second"),
        }
        assert all(value not in log_payload for value in sensitive_values)
    finally:
        if engine is not None:
            await engine.dispose()
        try:
            await _drop_database(admin, database)
        finally:
            await admin.close()
