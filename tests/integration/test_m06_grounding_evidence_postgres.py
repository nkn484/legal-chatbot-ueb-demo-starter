"""Opt-in PostgreSQL checks for the M06 grounding evidence read boundary."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select

from legal_chatbot.chat import ChatError, ChatErrorCode, ChatSettings, GroundingEvidenceRequest
from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.grounding_evidence import PostgresGroundingEvidenceAdapter
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
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
    retrieved_at: datetime,
) -> tuple[UUID, UUID, UUID]:
    version_id, provenance_id, chunk_id = uuid4(), uuid4(), uuid4()
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
            normalizer_version="m06-test",
            normalized_block_count=1,
        )
    )
    session.add(  # type: ignore[attr-defined]
        SourceProvenanceRecord(
            id=provenance_id,
            document_version_id=version_id,
            provenance_type=ProvenanceType.SOURCE_FETCH.value,
            source_id="TESTM06",
            transport="synthetic",
            operation="m06_grounding_test",
            retrieved_at=retrieved_at,
            tls_verified=True,
        )
    )
    session.add(  # type: ignore[attr-defined]
        DocumentChunk(
            id=chunk_id,
            document_version_id=version_id,
            ordinal=0,
            content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(f"{chunk_id}-{content}"),
            chunker_version="m06-test",
            locator={"version": version_number},
        )
    )
    return version_id, provenance_id, chunk_id


def _run(run_id: UUID) -> RetrievalRun:
    return RetrievalRun(
        id=run_id,
        strategy="postgresql_fts",
        strategy_version="v1",
        scope="LATEST_INGESTED",
        query_max_chars=100,
        top_k=2,
        candidate_count=2,
        citation_count=2,
        evidence_decision="EVIDENCE_AVAILABLE",
        evidence_reason="m06-test",
    )


@pytest.mark.asyncio
async def test_postgres_grounding_evidence_loads_exact_ordered_chain_without_writes() -> None:
    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_id = uuid4()
    run_ids: list[UUID] = []
    statements: list[str] = []
    listener_attached = False
    now = datetime.now(UTC)

    def count_statement(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del conn, cursor, parameters, context, executemany
        statements.append(statement)

    try:
        async with session_factory.begin() as session:
            session.add(
                LegalDocument(
                    id=document_id,
                    source_id="TESTM06",
                    external_id=f"m06-{document_id.hex}",
                )
            )
            historical_version, historical_provenance, historical_chunk = await _add_version(
                session,
                document_id=document_id,
                version_number=1,
                content=" historical citation survives newer versions ",
                retrieved_at=now - timedelta(days=3),
            )
            current_version, selected_provenance, current_chunk = await _add_version(
                session,
                document_id=document_id,
                version_number=2,
                content=" current grounding excerpt remains immutable ",
                retrieved_at=now - timedelta(days=2),
            )
            second_chunk = uuid4()
            second_text = " second grounding excerpt remains immutable "
            session.add(
                DocumentChunk(
                    id=second_chunk,
                    document_version_id=current_version,
                    ordinal=1,
                    content_text=second_text,
                    start_char=0,
                    end_char=len(second_text),
                    content_sha256=_digest(f"{second_chunk}-{second_text}"),
                    chunker_version="m06-test",
                    locator={"version": 2, "ordinal": 1},
                )
            )
            valid_run, historical_run, foreign_run, cross_version_run = (
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            )
            run_ids.extend((valid_run, historical_run, foreign_run, cross_version_run))
            session.add_all(tuple(_run(run_id) for run_id in run_ids))
            (
                first_citation,
                second_citation,
                historical_citation,
                foreign_citation,
                invalid_citation,
            ) = (
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
                uuid4(),
            )
            session.add_all(
                (
                    CitationRecord(
                        id=first_citation,
                        retrieval_run_id=valid_run,
                        document_chunk_id=current_chunk,
                        source_provenance_record_id=selected_provenance,
                        rank=1,
                        lexical_score=1.0,
                    ),
                    CitationRecord(
                        id=second_citation,
                        retrieval_run_id=valid_run,
                        document_chunk_id=second_chunk,
                        source_provenance_record_id=selected_provenance,
                        rank=2,
                        lexical_score=0.9,
                    ),
                    CitationRecord(
                        id=historical_citation,
                        retrieval_run_id=historical_run,
                        document_chunk_id=historical_chunk,
                        source_provenance_record_id=historical_provenance,
                        rank=1,
                        lexical_score=1.0,
                    ),
                    CitationRecord(
                        id=foreign_citation,
                        retrieval_run_id=foreign_run,
                        document_chunk_id=current_chunk,
                        source_provenance_record_id=selected_provenance,
                        rank=1,
                        lexical_score=1.0,
                    ),
                    CitationRecord(
                        id=invalid_citation,
                        retrieval_run_id=cross_version_run,
                        document_chunk_id=current_chunk,
                        source_provenance_record_id=historical_provenance,
                        rank=1,
                        lexical_score=1.0,
                    ),
                )
            )

        async with session_factory.begin() as session:
            await _add_version(
                session,
                document_id=document_id,
                version_number=3,
                content="newer version must not replace historical citations",
                retrieved_at=now,
            )
            session.add(
                SourceProvenanceRecord(
                    document_version_id=current_version,
                    provenance_type=ProvenanceType.SOURCE_FETCH.value,
                    source_id="TESTM06",
                    transport="synthetic",
                    operation="m06_backdated_provenance",
                    retrieved_at=now - timedelta(days=10),
                    tls_verified=True,
                )
            )

        async with session_factory() as session:
            before_runs = await session.scalar(select(func.count()).select_from(RetrievalRun))
            before_citations = await session.scalar(
                select(func.count()).select_from(CitationRecord)
            )
            before_documents = await session.scalar(select(func.count()).select_from(LegalDocument))

        event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
        listener_attached = True
        adapter = PostgresGroundingEvidenceAdapter(
            session_factory,
            ChatSettings(max_citations=2, excerpt_max_chars=10, total_evidence_max_chars=7),
        )
        evidence = await adapter.load(
            GroundingEvidenceRequest(
                retrieval_run_id=valid_run,
                citation_ids=(second_citation, first_citation),
            )
        )
        event.remove(engine.sync_engine, "before_cursor_execute", count_statement)
        listener_attached = False

        assert len(statements) == 1
        assert tuple(excerpt.citation.citation_id for excerpt in evidence.excerpts) == (
            second_citation,
            first_citation,
        )
        assert tuple(len(excerpt.text) for excerpt in evidence.excerpts) == (4, 3)
        assert evidence.excerpts[0].citation.source_provenance_record_id == selected_provenance
        assert evidence.excerpts[0].citation.document_version_id == current_version

        for request in (
            GroundingEvidenceRequest(
                retrieval_run_id=cross_version_run, citation_ids=(invalid_citation,)
            ),
            GroundingEvidenceRequest(
                retrieval_run_id=valid_run, citation_ids=(first_citation, foreign_citation)
            ),
            GroundingEvidenceRequest(
                retrieval_run_id=valid_run, citation_ids=(first_citation, uuid4())
            ),
        ):
            with pytest.raises(ChatError) as failure:
                await adapter.load(request)
            assert failure.value.code is ChatErrorCode.GROUNDING_FAILURE

        historical = await adapter.load(
            GroundingEvidenceRequest(
                retrieval_run_id=historical_run, citation_ids=(historical_citation,)
            )
        )
        assert historical.excerpts[0].citation.document_version_id == historical_version
        assert historical.excerpts[0].citation.source_provenance_record_id == historical_provenance

        async with session_factory() as session:
            after_runs = await session.scalar(select(func.count()).select_from(RetrievalRun))
            after_citations = await session.scalar(select(func.count()).select_from(CitationRecord))
            after_documents = await session.scalar(select(func.count()).select_from(LegalDocument))
        assert (after_runs, after_citations, after_documents) == (
            before_runs,
            before_citations,
            before_documents,
        )
    finally:
        if listener_attached:
            event.remove(engine.sync_engine, "before_cursor_execute", count_statement)
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
        await engine.dispose()
