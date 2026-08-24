"""Opt-in PostgreSQL checks for the M05 lexical retrieval vertical slice."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
)
from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
)
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


async def _add_version(
    session: object,
    *,
    document_id: UUID,
    version_number: int,
    content: str,
    chunks: tuple[UUID, ...],
    retrieved_at: datetime,
) -> tuple[UUID, UUID]:
    """Create dedicated test evidence with a predictable primary provenance record."""

    version_id = uuid4()
    provenance_id = uuid4()
    digest = _digest(f"{document_id}-{version_number}-{content}")
    session.add(  # type: ignore[attr-defined]
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            raw_html=f"<p>{content}</p>",
            normalized_text=content,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="m05-test",
            normalized_block_count=1,
        )
    )
    session.add(  # type: ignore[attr-defined]
        SourceProvenanceRecord(
            id=provenance_id,
            document_version_id=version_id,
            provenance_type=ProvenanceType.SOURCE_FETCH.value,
            source_id="TESTM05",
            transport="synthetic",
            operation="m05_retrieval_test",
            retrieved_at=retrieved_at,
            tls_verified=True,
        )
    )
    for ordinal, chunk_id in enumerate(chunks):
        session.add(  # type: ignore[attr-defined]
            DocumentChunk(
                id=chunk_id,
                document_version_id=version_id,
                ordinal=ordinal,
                content_text=content,
                start_char=0,
                end_char=len(content),
                content_sha256=_digest(f"{chunk_id}-{content}"),
                chunker_version="m05-test",
                locator={"ordinal": ordinal},
            )
        )
    return version_id, provenance_id


@pytest.mark.asyncio
async def test_postgres_lexical_retrieval_latest_scope_provenance_and_resolution() -> None:
    """Current chunks are ranked deterministically and old citations remain resolvable."""

    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_id = uuid4()
    external_id = f"m05-{document_id.hex}"
    run_ids: list[UUID] = []
    citation_ids: list[UUID] = []
    now = datetime.now(UTC)
    older_chunk = uuid4()
    tie_chunks = tuple(sorted((uuid4(), uuid4()), key=str))
    try:
        async with session_factory.begin() as session:
            session.add(
                LegalDocument(
                    id=document_id,
                    source_id="TESTM05",
                    external_id=external_id,
                )
            )
            _, old_provenance = await _add_version(
                session,
                document_id=document_id,
                version_number=1,
                content="m05obsolete old-only-token",
                chunks=(older_chunk,),
                retrieved_at=now - timedelta(days=2),
            )
            version_two, selected_provenance = await _add_version(
                session,
                document_id=document_id,
                version_number=2,
                content="m05current deterministic tie",
                chunks=tie_chunks,
                retrieved_at=now - timedelta(days=1),
            )
            session.add(
                SourceProvenanceRecord(
                    document_version_id=version_two,
                    provenance_type=ProvenanceType.SOURCE_FETCH.value,
                    source_id="TESTM05",
                    transport="synthetic",
                    operation="m05_later_provenance",
                    retrieved_at=now,
                    tls_verified=True,
                )
            )

        repository = PostgresLexicalRetrievalRepository(session_factory, ("TESTM05",))
        resolver = PostgresCitationResolver(session_factory)
        hit = await repository.retrieve_and_persist(RetrievalRequest(query="m05current", top_k=2))
        run_ids.append(hit.retrieval_run_id)
        citation_ids.extend(candidate.citation_id for candidate in hit.candidates)
        assert hit.decision is RetrievalDecision.EVIDENCE_AVAILABLE
        assert tuple(candidate.document_chunk_id for candidate in hit.candidates) == tie_chunks

        async with session_factory() as session:
            persisted_provenance = await session.scalars(
                select(CitationRecord.source_provenance_record_id).where(
                    CitationRecord.retrieval_run_id == hit.retrieval_run_id
                )
            )
            assert set(persisted_provenance) == {selected_provenance}

        no_hit = await repository.retrieve_and_persist(RetrievalRequest(query="old-only-token"))
        run_ids.append(no_hit.retrieval_run_id)
        assert no_hit.decision is RetrievalDecision.NO_RESULTS
        assert no_hit.candidates == ()

        for query in ('"m05current" | & ! ( )', "'m05current' --"):
            parsed = await repository.retrieve_and_persist(RetrievalRequest(query=query))
            run_ids.append(parsed.retrieval_run_id)

        resolved = await resolver.resolve(hit.candidates[0].citation_id, hit.retrieval_run_id)
        assert resolved.document_version_id == version_two
        assert resolved.source_provenance_record_id == selected_provenance
        assert not hasattr(resolved, "content_text")

        with pytest.raises(RetrievalError) as unknown:
            await resolver.resolve(uuid4(), hit.retrieval_run_id)
        assert unknown.value.code is RetrievalErrorCode.CITATION_NOT_FOUND
        with pytest.raises(RetrievalError) as wrong_run:
            await resolver.resolve(hit.candidates[0].citation_id, uuid4())
        assert wrong_run.value.code is RetrievalErrorCode.CITATION_RUN_MISMATCH

        async with session_factory.begin() as session:
            session.add(
                SourceProvenanceRecord(
                    document_version_id=version_two,
                    provenance_type=ProvenanceType.SOURCE_FETCH.value,
                    source_id="TESTM05",
                    transport="synthetic",
                    operation="m05_backdated_provenance",
                    retrieved_at=now - timedelta(days=3),
                    tls_verified=True,
                )
            )
        persisted_after_backfill = await resolver.resolve(
            hit.candidates[0].citation_id, hit.retrieval_run_id
        )
        assert persisted_after_backfill.source_provenance_record_id == selected_provenance

        async with session_factory.begin() as session:
            await _add_version(
                session,
                document_id=document_id,
                version_number=3,
                content="m05newer version after citation",
                chunks=(uuid4(),),
                retrieved_at=now + timedelta(days=1),
            )
            invalid_run = RetrievalRun(
                id=uuid4(),
                strategy="postgresql_fts",
                strategy_version="v1",
                scope="LATEST_INGESTED",
                query_max_chars=4000,
                top_k=1,
                candidate_count=1,
                citation_count=1,
                evidence_decision="EVIDENCE_AVAILABLE",
                evidence_reason="test",
            )
            invalid_citation = CitationRecord(
                id=uuid4(),
                retrieval_run_id=invalid_run.id,
                document_chunk_id=tie_chunks[0],
                source_provenance_record_id=old_provenance,
                rank=1,
                lexical_score=1.0,
            )
            session.add_all((invalid_run, invalid_citation))
            run_ids.append(invalid_run.id)
            citation_ids.append(invalid_citation.id)

        historical = await resolver.resolve(hit.candidates[0].citation_id, hit.retrieval_run_id)
        assert historical.document_version_id == version_two
        with pytest.raises(RetrievalError) as broken:
            await resolver.resolve(invalid_citation.id, invalid_run.id)
        assert broken.value.code is RetrievalErrorCode.INVALID_EVIDENCE_CHAIN
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                delete_citations = delete(CitationRecord).where(
                    CitationRecord.retrieval_run_id.in_(run_ids)
                )
                await session.execute(delete_citations)
            if run_ids:
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_repeatable_read_keeps_coherent_snapshot_during_new_version_commit() -> None:
    """A writer committing a newer version cannot create a mixed retrieval run."""

    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_id = uuid4()
    run_ids: list[UUID] = []
    initial_version: UUID | None = None
    snapshot_ready = asyncio.Event()
    newer_committed = asyncio.Event()
    try:
        async with session_factory.begin() as session:
            session.add(
                LegalDocument(
                    id=document_id,
                    source_id="TESTM05",
                    external_id=f"m05-snapshot-{document_id.hex}",
                )
            )
            initial_version, _ = await _add_version(
                session,
                document_id=document_id,
                version_number=1,
                content="m05 snapshot token",
                chunks=(uuid4(),),
                retrieved_at=datetime.now(UTC),
            )

        class _SnapshotRepository(PostgresLexicalRetrievalRepository):
            async def _retrieve_candidates(
                self, session: AsyncSession, request: RetrievalRequest
            ) -> tuple[_CandidateRow, ...]:
                await session.scalar(select(DocumentVersion.id).limit(1))
                snapshot_ready.set()
                await newer_committed.wait()
                return await super()._retrieve_candidates(session, request)

        retrieval_task = asyncio.create_task(
            _SnapshotRepository(session_factory, ("TESTM05",)).retrieve_and_persist(
                RetrievalRequest(query="m05 snapshot")
            )
        )
        await snapshot_ready.wait()
        async with session_factory.begin() as session:
            await _add_version(
                session,
                document_id=document_id,
                version_number=2,
                content="m05 snapshot token newer",
                chunks=(uuid4(),),
                retrieved_at=datetime.now(UTC) + timedelta(seconds=1),
            )
        newer_committed.set()
        result = await retrieval_task
        run_ids.append(result.retrieval_run_id)
        assert result.candidate_count == result.citation_count == len(result.candidates)
        async with session_factory() as session:
            cited_versions = await session.scalars(
                select(DocumentChunk.document_version_id)
                .join(CitationRecord, CitationRecord.document_chunk_id == DocumentChunk.id)
                .where(CitationRecord.retrieval_run_id == result.retrieval_run_id)
            )
            assert set(cited_versions) == {initial_version}
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_invalid_override_and_flush_failure_leave_no_partial_evidence() -> None:
    """A fabricated chain and a citation-flush failure both fail closed atomically."""

    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_id = uuid4()
    run_ids: list[UUID] = []
    try:

        class _MismatchedRepository(PostgresLexicalRetrievalRepository):
            async def _retrieve_candidates(
                self, session: AsyncSession, request: RetrievalRequest
            ) -> tuple[_CandidateRow, ...]:
                del session, request
                return (_CandidateRow(uuid4(), uuid4(), uuid4(), uuid4(), 1.0),)

        mismatched_repository = _MismatchedRepository(session_factory, ("TESTM05",))
        mismatched = await mismatched_repository.retrieve_and_persist(
            RetrievalRequest(query="m05 fabricated chain")
        )
        run_ids.append(mismatched.retrieval_run_id)
        assert mismatched.decision is RetrievalDecision.INVALID_EVIDENCE_CHAIN
        async with session_factory() as session:
            zero_citations = await session.scalar(
                select(func.count())
                .select_from(CitationRecord)
                .where(CitationRecord.retrieval_run_id == mismatched.retrieval_run_id)
            )
            assert zero_citations == 0

        chunk_id = uuid4()
        now = datetime.now(UTC)
        async with session_factory.begin() as session:
            session.add(
                LegalDocument(
                    id=document_id,
                    source_id="TESTM05",
                    external_id=f"m05-atomic-{document_id.hex}",
                )
            )
            await _add_version(
                session,
                document_id=document_id,
                version_number=1,
                content="m05 atomic failure token",
                chunks=(chunk_id,),
                retrieved_at=now,
            )

        class _FlushFailingRepository(PostgresLexicalRetrievalRepository):
            async def _persist_result(
                self,
                session: AsyncSession,
                request: RetrievalRequest,
                candidates: tuple[_CandidateRow, ...],
                decision: RetrievalDecision,
                reason: RetrievalReason,
                strategy_version: str,
            ) -> RetrievalResult:
                original_flush = session.flush
                flush_count = 0

                async def fail_citation_flush() -> None:
                    nonlocal flush_count
                    flush_count += 1
                    if flush_count == 2:
                        raise RuntimeError("test-only flush failure")
                    await original_flush()

                session.flush = fail_citation_flush  # type: ignore[method-assign]
                return await super()._persist_result(
                    session, request, candidates, decision, reason, strategy_version
                )

        async with session_factory() as session:
            before_runs = await session.scalar(select(func.count()).select_from(RetrievalRun))
            before_citations = await session.scalar(
                select(func.count()).select_from(CitationRecord)
            )
        with pytest.raises(RetrievalError) as failure:
            await _FlushFailingRepository(session_factory, ("TESTM05",)).retrieve_and_persist(
                RetrievalRequest(query="m05 atomic")
            )
        assert failure.value.code is RetrievalErrorCode.PERSISTENCE_FAILURE
        async with session_factory() as session:
            after_runs = await session.scalar(select(func.count()).select_from(RetrievalRun))
            after_citations = await session.scalar(select(func.count()).select_from(CitationRecord))
        assert after_runs == before_runs
        assert after_citations == before_citations
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
        await engine.dispose()
