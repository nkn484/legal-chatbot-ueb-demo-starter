"""Opt-in PostgreSQL coverage for M07 conversation repository transactions."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.errors import ConversationError, ConversationErrorCode
from legal_chatbot.conversation.models import (
    ConversationExchangeStatus,
    ConversationRequest,
    ConversationReservationResult,
    ConversationStateUpdate,
)
from legal_chatbot.conversation.orm import (
    Conversation,
    ConversationExchange,
    ConversationExchangeReference,
)
from legal_chatbot.conversation.repository import PostgresConversationRepository
from legal_chatbot.core.config import Settings
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.models import ResolvedCitation, RetrievalDecision, RetrievalReason
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


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


async def _drop_database(connection: asyncpg.Connection, database_name: str) -> None:
    await connection.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        database_name,
    )
    await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


def _run_alembic(arguments: list[str], database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, "Alembic setup command failed"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


async def _placeholder_no_results_run(factory, now: datetime) -> UUID:
    """Seed a repository-only M05 placeholder without any citation fixture."""

    run = RetrievalRun(
        id=uuid4(),
        strategy="m07-placeholder",
        strategy_version="1",
        scope="LATEST_INGESTED",
        query_max_chars=1,
        top_k=1,
        candidate_count=0,
        citation_count=0,
        evidence_decision="NO_RESULTS",
        evidence_reason=RetrievalReason.NO_LEXICAL_MATCH.value,
        created_at=now,
    )
    async with factory() as session:
        async with session.begin():
            session.add(run)
    return run.id


async def _m05_evidence(factory, now: datetime) -> tuple[UUID, ResolvedCitation]:
    """Seed one valid M05 run and citation chain owned by this disposable database."""

    run_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    provenance_id = uuid4()
    chunk_id = uuid4()
    citation_id = uuid4()
    digest = "0" * 64
    async with factory() as session:
        async with session.begin():
            session.add_all(
                (
                    RetrievalRun(
                        id=run_id,
                        strategy="m07-evidence",
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
                        id=document_id,
                        source_id="M07TEST",
                        external_id=str(uuid4()),
                    ),
                    DocumentVersion(
                        id=version_id,
                        document_id=document_id,
                        version_number=1,
                        raw_html="<p>Evidence</p>",
                        normalized_text="Evidence",
                        snapshot_sha256=digest,
                        source_content_sha256=digest,
                        normalized_text_sha256=digest,
                        normalizer_version="m07-test",
                        normalized_block_count=1,
                    ),
                    SourceProvenanceRecord(
                        id=provenance_id,
                        document_version_id=version_id,
                        provenance_type=ProvenanceType.SOURCE_FETCH.value,
                        source_id="M07TEST",
                        transport="test",
                        operation="m07_repository_test",
                        retrieved_at=now,
                        tls_verified=True,
                    ),
                    DocumentChunk(
                        id=chunk_id,
                        document_version_id=version_id,
                        ordinal=0,
                        content_text="Evidence",
                        start_char=0,
                        end_char=8,
                        content_sha256=digest,
                        chunker_version="m07-test",
                    ),
                )
            )
            await session.flush()
            session.add(
                CitationRecord(
                    id=citation_id,
                    retrieval_run_id=run_id,
                    document_chunk_id=chunk_id,
                    source_provenance_record_id=provenance_id,
                    rank=1,
                    lexical_score=1.0,
                )
            )
    return run_id, ResolvedCitation(
        citation_id=citation_id,
        retrieval_run_id=run_id,
        document_chunk_id=chunk_id,
        document_version_id=version_id,
        document_id=document_id,
        source_provenance_record_id=provenance_id,
        source_id="M07TEST",
        external_id="m07-evidence",
    )


async def _seed_terminal_exchanges(
    factory,
    conversation_id: UUID,
    retrieval_run_id: UUID,
    now: datetime,
    *,
    count: int,
) -> tuple[UUID, ...]:
    exchange_ids = tuple(uuid4() for _ in range(count))
    async with factory() as session:
        async with session.begin():
            session.add_all(
                ConversationExchange(
                    id=exchange_id,
                    conversation_id=conversation_id,
                    delivery_key_sha256=f"{ordinal:064x}",
                    ordinal=ordinal,
                    status=ConversationExchangeStatus.COMPLETED.value,
                    user_text=f"Question {ordinal}",
                    assistant_text=f"Answer {ordinal}",
                    chat_outcome=ChatOutcome.CLARIFICATION.value,
                    chat_reason=ChatReasonCode.NO_RESULTS.value,
                    retrieval_run_id=retrieval_run_id,
                    completed_at=now,
                )
                for ordinal, exchange_id in enumerate(exchange_ids, start=1)
            )
    return exchange_ids


def _citation(run_id: UUID, *, document_id: UUID | None = None) -> ResolvedCitation:
    return ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=run_id,
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=document_id or uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="M07TEST",
        external_id="m07-test",
    )


def _answer(
    run_id: UUID, *, citations: tuple[ResolvedCitation, ...] | None = None
) -> GroundedChatResult:
    if citations is None:
        first = _citation(run_id)
        citations = (first, _citation(run_id, document_id=first.document_id))
    return GroundedChatResult(
        outcome=ChatOutcome.ANSWER,
        reason=ChatReasonCode.ANSWER_GROUNDED,
        answer="Grounded answer.",
        retrieval_run_id=run_id,
        citations=citations,
        provider="test-provider",
        model="test-model",
    )


@pytest.fixture
async def repository():
    source_url = make_url(Settings().database_url.get_secret_value())
    database_name = f"m07_repository_{uuid4().hex}"
    database_url = source_url.set(database=database_name).render_as_string(hide_password=False)
    admin_connection = await _connect(source_url, "postgres")
    await _drop_database(admin_connection, database_name)
    await admin_connection.execute(f'CREATE DATABASE "{database_name}"')
    _run_alembic(["upgrade", "head"], database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield PostgresConversationRepository(factory, ConversationSettings()), factory
    finally:
        await engine.dispose()
        try:
            await _drop_database(admin_connection, database_name)
        finally:
            await admin_connection.close()


@pytest.mark.asyncio
async def test_reserve_serializes_same_and_different_deliveries(repository) -> None:
    repo, factory = repository
    now = _now()
    conversation_id = (await repo.create_conversation(now)).conversation_id
    request = ConversationRequest(
        conversation_id=conversation_id, delivery_id="same", text="Question"
    )

    first, second = await asyncio.gather(repo.reserve(request, now), repo.reserve(request, now))

    assert {first.status.value, second.status.value} == {"RESERVED", "DUPLICATE_PROCESSING"}
    reserved = next(result for result in (first, second) if result.reservation is not None)
    duplicate_processing = next(
        result for result in (first, second) if result.status.value == "DUPLICATE_PROCESSING"
    )
    assert reserved.reservation is not None
    assert duplicate_processing.conversation_id == conversation_id
    assert duplicate_processing.exchange_id == reserved.reservation.exchange_id
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ConversationExchange)
                .where(ConversationExchange.conversation_id == conversation_id)
            )
            == 1
        )

    other_conversation = (await repo.create_conversation(now)).conversation_id
    different = await asyncio.gather(
        repo.reserve(
            ConversationRequest(conversation_id=other_conversation, delivery_id="one", text="One"),
            now,
        ),
        repo.reserve(
            ConversationRequest(conversation_id=other_conversation, delivery_id="two", text="Two"),
            now,
        ),
        return_exceptions=True,
    )
    assert (
        sum(
            isinstance(result, ConversationReservationResult) and result.status.value == "RESERVED"
            for result in different
        )
        == 1
    )
    assert any(
        isinstance(result, ConversationError) and result.code is ConversationErrorCode.BUSY
        for result in different
    )
    async with factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ConversationExchange)
                .where(
                    ConversationExchange.conversation_id == other_conversation,
                    ConversationExchange.status == "PROCESSING",
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_complete_replay_stale_conflict_and_bounded_snapshot(repository) -> None:
    repo, factory = repository
    now = _now()
    run_id = await _placeholder_no_results_run(factory, now)
    conversation_id = (await repo.create_conversation(now)).conversation_id
    request = ConversationRequest(
        conversation_id=conversation_id, delivery_id="complete", text="Question"
    )
    reservation = (await repo.reserve(request, now)).reservation
    assert reservation is not None

    completed = await repo.complete(
        reservation,
        _answer(run_id),
        ConversationStateUpdate(expected_state_version=reservation.expected_state_version),
        now,
    )
    replay = await repo.reserve(request, now)
    assert replay.status.value == "DUPLICATE_COMPLETED"
    assert replay.completed == completed
    assert [reference.kind.value for reference in completed.references] == [
        "CITATION",
        "CITATION",
        "DOCUMENT",
    ]
    async with factory() as session:
        assert (
            await session.scalar(
                select(Conversation.state_version).where(Conversation.id == conversation_id)
            )
            == 1
        )

    clarification_conversation = (await repo.create_conversation(now)).conversation_id
    clarification_reservation = (
        await repo.reserve(
            ConversationRequest(
                conversation_id=clarification_conversation,
                delivery_id="clarification",
                text="Clarify",
            ),
            now,
        )
    ).reservation
    assert clarification_reservation is not None
    clarification = await repo.complete(
        clarification_reservation,
        GroundedChatResult(
            outcome=ChatOutcome.CLARIFICATION,
            reason=ChatReasonCode.NO_RESULTS,
            answer="Please clarify.",
            retrieval_run_id=run_id,
        ),
        ConversationStateUpdate(expected_state_version=0),
        now,
    )
    refusal_conversation = (await repo.create_conversation(now)).conversation_id
    refusal_reservation = (
        await repo.reserve(
            ConversationRequest(
                conversation_id=refusal_conversation, delivery_id="refusal", text="Refuse"
            ),
            now,
        )
    ).reservation
    assert refusal_reservation is not None
    refusal = await repo.complete(
        refusal_reservation,
        GroundedChatResult(
            outcome=ChatOutcome.REFUSAL,
            reason=ChatReasonCode.RETRIEVAL_FAILURE,
            answer="Unable to retrieve evidence.",
        ),
        ConversationStateUpdate(expected_state_version=0),
        now,
    )
    assert clarification.references == ()
    assert refusal.references == ()

    stale_request = ConversationRequest(
        conversation_id=conversation_id, delivery_id="stale", text="Stale"
    )
    stale = (await repo.reserve(stale_request, now)).reservation
    assert stale is not None
    later = now + timedelta(seconds=ConversationSettings().processing_lease_seconds + 1)
    stale_replay = await repo.reserve(stale_request, later)
    assert stale_replay.status.value == "DUPLICATE_TERMINAL"
    assert stale_replay.conversation_id == conversation_id
    assert stale_replay.exchange_id == stale.exchange_id
    assert (
        await repo.reserve(
            ConversationRequest(conversation_id=conversation_id, delivery_id="fresh", text="Fresh"),
            later,
        )
    ).status.value == "RESERVED"

    conflict_conversation = (await repo.create_conversation(now)).conversation_id
    conflict_reservation = (
        await repo.reserve(
            ConversationRequest(
                conversation_id=conflict_conversation, delivery_id="conflict", text="Conflict"
            ),
            now,
        )
    ).reservation
    assert conflict_reservation is not None
    async with factory() as session:
        async with session.begin():
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conflict_conversation)
                .values(state_version=1)
            )
    with pytest.raises(ConversationError) as conflict_error:
        await repo.complete(
            conflict_reservation,
            _answer(run_id),
            ConversationStateUpdate(expected_state_version=0),
            now,
        )
    assert conflict_error.value.code is ConversationErrorCode.CONFLICT
    async with factory() as session:
        assert (
            await session.scalar(
                select(ConversationExchange.status).where(
                    ConversationExchange.id == conflict_reservation.exchange_id
                )
            )
            == ConversationExchangeStatus.PROCESSING.value
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ConversationExchangeReference)
                .where(
                    ConversationExchangeReference.exchange_id == conflict_reservation.exchange_id
                )
            )
            == 0
        )

    bounded_conversation = (await repo.create_conversation(now)).conversation_id
    async with factory() as session:
        async with session.begin():
            session.add_all(
                ConversationExchange(
                    id=uuid4(),
                    conversation_id=bounded_conversation,
                    delivery_key_sha256=f"{ordinal:064x}",
                    ordinal=ordinal,
                    status=ConversationExchangeStatus.COMPLETED.value,
                    user_text=f"Question {ordinal}",
                    assistant_text=f"Answer {ordinal}",
                    chat_outcome=ChatOutcome.CLARIFICATION.value,
                    chat_reason=ChatReasonCode.NO_RESULTS.value,
                    retrieval_run_id=run_id,
                    completed_at=now,
                )
                for ordinal in range(1, 5)
            )
    snapshot = await repo.load_snapshot(bounded_conversation, now)
    assert len(snapshot.recent_turns) == ConversationSettings().recent_completed_turn_limit
    assert [turn.text for turn in snapshot.recent_turns] == [
        "Question 3",
        "Answer 3",
        "Question 4",
        "Answer 4",
    ]


@pytest.mark.asyncio
async def test_purge_is_m07_only_and_m05_run_remains_protected_until_conversation_is_removed(
    repository,
) -> None:
    repo, factory = repository
    now = _now()
    run_id, citation = await _m05_evidence(factory, now)
    conversation_id = (await repo.create_conversation(now)).conversation_id
    reservation = (
        await repo.reserve(
            ConversationRequest(
                conversation_id=conversation_id, delivery_id="purge", text="Question"
            ),
            now,
        )
    ).reservation
    assert reservation is not None
    await repo.complete(
        reservation,
        _answer(run_id, citations=(citation,)),
        ConversationStateUpdate(expected_state_version=0),
        now,
    )

    async with factory() as session:
        with pytest.raises(IntegrityError):
            async with session.begin():
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id == run_id))
        async with session.begin():
            await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    created_at=now - timedelta(seconds=2),
                    expires_at=now - timedelta(seconds=1),
                )
            )
    assert await repo.purge_expired(now, 1) == 1
    async with factory() as session:
        assert (
            await session.scalar(select(RetrievalRun.id).where(RetrievalRun.id == run_id)) == run_id
        )
        await session.rollback()
        async with session.begin():
            await session.execute(
                delete(CitationRecord).where(CitationRecord.id == citation.citation_id)
            )
            await session.execute(delete(RetrievalRun).where(RetrievalRun.id == run_id))


@pytest.mark.asyncio
async def test_reservation_compaction_plan_deletes_only_authorized_oldest_terminal_exchange(
    repository,
) -> None:
    repo, factory = repository
    now = _now()
    run_id, citation = await _m05_evidence(factory, now)
    conversation_id = (await repo.create_conversation(now)).conversation_id
    exchange_ids = await _seed_terminal_exchanges(factory, conversation_id, run_id, now, count=32)

    reservation = (
        await repo.reserve(
            ConversationRequest(
                conversation_id=conversation_id, delivery_id="compaction", text="Question 33"
            ),
            now,
        )
    ).reservation
    assert reservation is not None
    assert reservation.compaction_plan.exchange_ids == (exchange_ids[0],)
    assert reservation.compaction_plan.candidates[0].ordinal == 1

    await repo.complete(
        reservation,
        GroundedChatResult(
            outcome=ChatOutcome.CLARIFICATION,
            reason=ChatReasonCode.NO_RESULTS,
            answer="Please clarify.",
            retrieval_run_id=run_id,
        ),
        ConversationStateUpdate(
            expected_state_version=reservation.expected_state_version,
            rolling_summary="Compacted summary.",
            compacted_exchange_ids=reservation.compaction_plan.exchange_ids,
        ),
        now,
    )
    async with factory() as session:
        assert (
            await session.scalar(
                select(Conversation.rolling_summary).where(Conversation.id == conversation_id)
            )
            == "Compacted summary."
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ConversationExchange)
                .where(
                    ConversationExchange.conversation_id == conversation_id,
                    ConversationExchange.status.in_(("COMPLETED", "FAILED", "ABANDONED")),
                )
            )
            == 32
        )
        assert (
            await session.scalar(
                select(ConversationExchange.id).where(ConversationExchange.id == exchange_ids[0])
            )
            is None
        )
        assert (
            await session.scalar(select(RetrievalRun.id).where(RetrievalRun.id == run_id)) == run_id
        )
        assert (
            await session.scalar(
                select(CitationRecord.id).where(CitationRecord.id == citation.citation_id)
            )
            == citation.citation_id
        )


@pytest.mark.asyncio
async def test_mismatched_compaction_ids_roll_back_current_completion_and_deletion(
    repository,
) -> None:
    repo, factory = repository
    now = _now()
    run_id = await _placeholder_no_results_run(factory, now)
    conversation_id = (await repo.create_conversation(now)).conversation_id
    exchange_ids = await _seed_terminal_exchanges(factory, conversation_id, run_id, now, count=32)
    reservation = (
        await repo.reserve(
            ConversationRequest(
                conversation_id=conversation_id, delivery_id="mismatch", text="Question 33"
            ),
            now,
        )
    ).reservation
    assert reservation is not None

    with pytest.raises(ConversationError) as error:
        await repo.complete(
            reservation,
            GroundedChatResult(
                outcome=ChatOutcome.CLARIFICATION,
                reason=ChatReasonCode.NO_RESULTS,
                answer="Please clarify.",
                retrieval_run_id=run_id,
            ),
            ConversationStateUpdate(expected_state_version=0, compacted_exchange_ids=()),
            now,
        )
    assert error.value.code is ConversationErrorCode.CONFLICT
    async with factory() as session:
        assert (
            await session.scalar(
                select(ConversationExchange.status).where(
                    ConversationExchange.id == reservation.exchange_id
                )
            )
            == ConversationExchangeStatus.PROCESSING.value
        )
        assert (
            await session.scalar(
                select(ConversationExchange.id).where(ConversationExchange.id == exchange_ids[0])
            )
            == exchange_ids[0]
        )
