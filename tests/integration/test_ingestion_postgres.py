"""Opt-in M04 persistence checks against migrated PostgreSQL and pgvector."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from sqlalchemy import delete, func, select, text

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.ingestion import (
    DeterministicChunker,
    HTMLNormalizer,
    IngestionService,
    IngestionSettings,
    LocalHashEmbeddingAdapter,
)
from legal_chatbot.sources.models import (
    LegalDocumentSnapshot,
    ProvenanceType,
    SourceProvenance,
    TransportTrustMode,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_SOURCE_ID = "TESTM04"
_EXTERNAL_ID = "m04-synthetic-document"
_CONCURRENT_EXTERNAL_ID = "m04-concurrent-document"


def _snapshot(
    *, html: str, title: str = "Synthetic M04", external_id: str = _EXTERNAL_ID
) -> LegalDocumentSnapshot:
    return LegalDocumentSnapshot(
        source_id=_SOURCE_ID,
        external_id=external_id,
        title=title,
        content_html=html,
        content_sha256=sha256(html.encode("utf-8")).hexdigest(),
        provenance=SourceProvenance(
            provenance_type=ProvenanceType.SOURCE_FETCH,
            source_id=_SOURCE_ID,
            transport="synthetic",
            operation="integration_test",
            retrieved_at=datetime.now(UTC),
            tls_verified=True,
        ),
    )


@pytest.mark.asyncio
async def test_postgres_ingestion_is_immutable_idempotent_and_vector_backed() -> None:
    """Clean only the dedicated allowlisted test document and verify its evidence chain."""
    from legal_chatbot.documents.repository import DocumentRepository

    settings = Settings()
    ingestion_settings = IngestionSettings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    service = IngestionService(
        DocumentRepository(session_factory),
        HTMLNormalizer(),
        DeterministicChunker(ingestion_settings),
        LocalHashEmbeddingAdapter(ingestion_settings),
        ingestion_settings,
    )
    try:
        async with session_factory.begin() as session:
            await session.execute(
                delete(LegalDocument).where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _EXTERNAL_ID,
                )
            )

        first_snapshot = _snapshot(html="<p>First synthetic legal provision.</p>")
        created = await service.ingest_snapshot(first_snapshot)
        unchanged = await service.ingest_snapshot(first_snapshot)
        content_changed = await service.ingest_snapshot(
            _snapshot(html="<p>Changed synthetic legal provision.</p>")
        )
        metadata_snapshot = _snapshot(
            html="<p>Changed synthetic legal provision.</p>", title="Changed metadata"
        )
        metadata_changed = await service.ingest_snapshot(metadata_snapshot)
        profile_settings = IngestionSettings(INGESTION_CHUNK_MAX_CHARS=1_300)
        profile_service = IngestionService(
            DocumentRepository(session_factory),
            HTMLNormalizer(),
            DeterministicChunker(profile_settings),
            LocalHashEmbeddingAdapter(profile_settings),
            profile_settings,
        )
        profile_changed = await profile_service.ingest_snapshot(metadata_snapshot)

        assert created.outcome.value == "created"
        assert unchanged.outcome.value == "unchanged"
        assert content_changed.outcome.value == "created"
        assert metadata_changed.outcome.value == "created"
        assert profile_changed.outcome.value == "created"
        document_ids = {
            created.document_id,
            content_changed.document_id,
            metadata_changed.document_id,
            profile_changed.document_id,
        }
        assert len(document_ids) == 1
        version_numbers = [
            created.version_number,
            content_changed.version_number,
            metadata_changed.version_number,
            profile_changed.version_number,
        ]
        assert version_numbers == [1, 2, 3, 4]

        async with session_factory() as session:
            chain_count = await session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
                .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
                .join(
                    SourceProvenanceRecord,
                    SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                )
                .where(LegalDocument.id == created.document_id)
            )
            embedding_count = await session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
                .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
                .where(DocumentVersion.document_id == created.document_id)
            )
            dimensions = await session.scalars(
                select(ChunkEmbedding.dimension)
                .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
                .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
                .where(DocumentVersion.document_id == created.document_id)
            )
            hnsw_index = await session.scalar(
                text("SELECT to_regclass('public.ix_chunk_embeddings_embedding_hnsw_cosine')")
            )
            provenance = await session.scalar(
                select(SourceProvenanceRecord)
                .join(
                    DocumentVersion,
                    SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                )
                .where(DocumentVersion.id == created.document_version_id)
            )

        expected_embedding_count = sum(
            result.chunk_count
            for result in (created, content_changed, metadata_changed, profile_changed)
        )
        assert chain_count == embedding_count == expected_embedding_count
        assert set(dimensions.all()) == {384}
        assert hnsw_index == "ix_chunk_embeddings_embedding_hnsw_cosine"
        assert provenance is not None
        assert (
            provenance.transport_trust_mode,
            provenance.tls_chain_verified,
            provenance.tls_hostname_verified,
            provenance.tls_verified,
        ) == (TransportTrustMode.STRICT_TLS.value, True, True, True)
        trust_digest = sha256(b"direct-orm-tofu-trust").hexdigest()
        certificate_not_before = datetime(2026, 6, 10, tzinfo=UTC)
        async with session_factory.begin() as session:
            session.add_all(
                (
                    SourceProvenanceRecord(
                        document_version_id=created.document_version_id,
                        provenance_type="source_fetch",
                        source_id=_SOURCE_ID,
                        transport="synthetic",
                        operation="direct_orm_strict",
                        retrieved_at=datetime.now(UTC),
                        tls_verified=True,
                    ),
                    SourceProvenanceRecord(
                        document_version_id=created.document_version_id,
                        provenance_type="source_fetch",
                        source_id=_SOURCE_ID,
                        transport="synthetic",
                        operation="direct_orm_legacy",
                        retrieved_at=datetime.now(UTC),
                        tls_verified=False,
                    ),
                    SourceProvenanceRecord(
                        document_version_id=created.document_version_id,
                        provenance_type="source_fetch",
                        source_id=_SOURCE_ID,
                        transport="synthetic",
                        operation="direct_orm_tofu",
                        retrieved_at=datetime.now(UTC),
                        tls_verified=False,
                        transport_trust_mode=TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION.value,
                        tls_chain_verified=True,
                        tls_hostname_verified=False,
                        trust_exception_id="test-tofu-exception",
                        trust_exception_digest=trust_digest,
                        policy_id="test-policy",
                        policy_version=1,
                        compiled_policy_digest=trust_digest,
                        registry_snapshot_digest=trust_digest,
                        pin_set_id="test-pin-set",
                        pin_set_version=1,
                        pin_set_digest=trust_digest,
                        matched_pin_id="test-matched-pin",
                        peer_certificate_not_before=certificate_not_before,
                        peer_certificate_not_after=certificate_not_before + timedelta(days=30),
                        acquisition_correlation_id="test-acquisition-1",
                    ),
                )
            )
        async with session_factory() as session:
            direct_trust_rows = {
                row.operation: (
                    row.transport_trust_mode,
                    row.tls_chain_verified,
                    row.tls_hostname_verified,
                    row.tls_verified,
                )
                for row in (
                    await session.scalars(
                        select(SourceProvenanceRecord).where(
                            SourceProvenanceRecord.document_version_id
                            == created.document_version_id,
                            SourceProvenanceRecord.operation.like("direct_orm_%"),
                        )
                    )
                ).all()
            }
        assert direct_trust_rows == {
            "direct_orm_strict": ("STRICT_TLS", True, True, True),
            "direct_orm_legacy": ("LEGACY_UNVERIFIED", False, False, False),
            "direct_orm_tofu": (
                "USER_APPROVED_TOFU_PINNED_EXCEPTION",
                True,
                False,
                False,
            ),
        }
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                delete(LegalDocument).where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _EXTERNAL_ID,
                )
            )
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_concurrent_writers_create_one_immutable_version() -> None:
    """Serialize two independent repositories writing the same dedicated snapshot."""
    from legal_chatbot.documents.repository import DocumentRepository

    settings = Settings()
    ingestion_settings = IngestionSettings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    snapshot = _snapshot(
        html="<p>Concurrent synthetic legal provision.</p>",
        external_id=_CONCURRENT_EXTERNAL_ID,
    )
    first_service = IngestionService(
        DocumentRepository(session_factory),
        HTMLNormalizer(),
        DeterministicChunker(ingestion_settings),
        LocalHashEmbeddingAdapter(ingestion_settings),
        ingestion_settings,
    )
    second_service = IngestionService(
        DocumentRepository(session_factory),
        HTMLNormalizer(),
        DeterministicChunker(ingestion_settings),
        LocalHashEmbeddingAdapter(ingestion_settings),
        ingestion_settings,
    )
    try:
        async with session_factory.begin() as session:
            await session.execute(
                delete(LegalDocument).where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )

        results = await asyncio.gather(
            first_service.ingest_snapshot(snapshot), second_service.ingest_snapshot(snapshot)
        )
        outcomes = sorted(result.outcome.value for result in results)
        created = next(result for result in results if result.outcome.value == "created")

        assert outcomes == ["created", "unchanged"]
        async with session_factory() as session:
            document_count = await session.scalar(
                select(func.count())
                .select_from(LegalDocument)
                .where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )
            version_count = await session.scalar(
                select(func.count())
                .select_from(DocumentVersion)
                .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
                .where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )
            provenance_count = await session.scalar(
                select(func.count())
                .select_from(SourceProvenanceRecord)
                .join(
                    DocumentVersion,
                    SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                )
                .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
                .where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )
            chunk_count = await session.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
                .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
                .where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )
            embedding_count = await session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
                .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
                .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
                .where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )

        assert document_count == version_count == provenance_count == 1
        assert chunk_count == embedding_count == created.chunk_count == created.embedding_count
    finally:
        async with session_factory.begin() as session:
            await session.execute(
                delete(LegalDocument).where(
                    LegalDocument.source_id == _SOURCE_ID,
                    LegalDocument.external_id == _CONCURRENT_EXTERNAL_ID,
                )
            )
        await engine.dispose()
