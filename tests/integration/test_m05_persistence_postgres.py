"""Opt-in M05 persistence checks against migrated PostgreSQL."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
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


@pytest.mark.asyncio
async def test_postgres_generated_vector_gin_index_and_citation_restrict_deletion() -> None:
    """Generated lexical evidence is indexed and protects cited source evidence from deletion."""
    settings = Settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    document_id = uuid4()
    version_id = uuid4()
    provenance_id = uuid4()
    chunk_id = uuid4()
    run_id = uuid4()
    citation_id = uuid4()
    now = datetime.now(UTC)
    content = "Generated lexical evidence"
    digest = "a" * 64

    try:
        async with session_factory.begin() as session:
            session.add_all(
                [
                    LegalDocument(
                        id=document_id,
                        source_id="TESTM05",
                        external_id=f"m05-{document_id.hex}",
                    ),
                    DocumentVersion(
                        id=version_id,
                        document_id=document_id,
                        version_number=1,
                        raw_html=f"<p>{content}</p>",
                        normalized_text=content,
                        snapshot_sha256=digest,
                        source_content_sha256=digest,
                        normalized_text_sha256=digest,
                        normalizer_version="test-v1",
                        normalized_block_count=1,
                    ),
                    SourceProvenanceRecord(
                        id=provenance_id,
                        document_version_id=version_id,
                        provenance_type=ProvenanceType.SOURCE_FETCH.value,
                        source_id="TESTM05",
                        transport="synthetic",
                        operation="integration_test",
                        retrieved_at=now,
                        tls_verified=True,
                    ),
                    DocumentChunk(
                        id=chunk_id,
                        document_version_id=version_id,
                        ordinal=0,
                        content_text=content,
                        start_char=0,
                        end_char=len(content),
                        content_sha256=digest,
                        chunker_version="test-v1",
                    ),
                    RetrievalRun(
                        id=run_id,
                        strategy="postgresql_fts",
                        strategy_version="v1",
                        scope="LATEST_INGESTED",
                        query_max_chars=256,
                        top_k=1,
                        candidate_count=1,
                        citation_count=1,
                        evidence_decision="EVIDENCE_AVAILABLE",
                        evidence_reason="synthetic evidence",
                    ),
                    CitationRecord(
                        id=citation_id,
                        retrieval_run_id=run_id,
                        document_chunk_id=chunk_id,
                        source_provenance_record_id=provenance_id,
                        rank=1,
                        lexical_score=1.0,
                    ),
                ]
            )
            await session.flush()

            generated_vector = await session.scalar(
                text("SELECT search_vector::text FROM document_chunks WHERE id = :chunk_id"),
                {"chunk_id": chunk_id},
            )
            gin_index = await session.scalar(
                text("SELECT to_regclass('public.ix_document_chunks_search_vector_gin')")
            )
            assert generated_vector is not None
            assert "generated" in generated_vector
            assert gin_index == "ix_document_chunks_search_vector_gin"

            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(delete(RetrievalRun).where(RetrievalRun.id == run_id))

            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await session.execute(delete(DocumentChunk).where(DocumentChunk.id == chunk_id))

            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    delete_provenance = delete(SourceProvenanceRecord).where(
                        SourceProvenanceRecord.id == provenance_id
                    )
                    await session.execute(delete_provenance)

            citation_record_id = await session.scalar(
                select(CitationRecord.id).where(CitationRecord.id == citation_id)
            )
            assert citation_record_id
            await session.execute(delete(CitationRecord).where(CitationRecord.id == citation_id))
            await session.execute(delete(RetrievalRun).where(RetrievalRun.id == run_id))
            await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
    finally:
        await engine.dispose()
