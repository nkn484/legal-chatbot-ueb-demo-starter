"""PostgreSQL persistence boundary for immutable document ingestion."""

from __future__ import annotations

from hashlib import sha256
from math import fsum, isfinite, sqrt
from re import fullmatch
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.metadata_normalization import normalize_document_number
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.ingestion.models import (
    ChunkDraft,
    EmbeddingKind,
    IngestionOutcome,
    IngestionResult,
    NormalizedDocument,
)
from legal_chatbot.sources.models import LegalDocumentSnapshot

_SHA256_PATTERN = r"[0-9a-f]{64}"
_VECTOR_DIMENSION = 384
_ResultEmbeddingModelId = Literal["local-hash-v1"]


def _validate_sha256(value: str, label: str) -> None:
    if fullmatch(_SHA256_PATTERN, value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 hexadecimal digest")


def _validate_payload(
    snapshot: LegalDocumentSnapshot,
    normalized: NormalizedDocument,
    chunks: tuple[ChunkDraft, ...],
    vectors: tuple[tuple[float, ...], ...],
    snapshot_sha256: str,
    embedding_model_id: str,
) -> None:
    """Validate only bounded metadata and content integrity before opening a session."""

    _validate_sha256(snapshot_sha256, "snapshot_sha256")
    _validate_sha256(snapshot.content_sha256, "source_content_sha256")
    _validate_sha256(normalized.sha256, "normalized_text_sha256")

    if sha256(snapshot.content_html.encode("utf-8")).hexdigest() != snapshot.content_sha256:
        raise ValueError("source content hash does not match raw HTML")
    if sha256(normalized.text.encode("utf-8")).hexdigest() != normalized.sha256:
        raise ValueError("normalized text hash does not match normalized text")
    if not normalized.blocks:
        raise ValueError("normalized document must contain at least one block")
    if len(chunks) != len(vectors):
        raise ValueError("chunk and vector counts must match")
    if not chunks:
        raise ValueError("at least one chunk is required")
    if not embedding_model_id or len(embedding_model_id) > 256:
        raise ValueError("embedding_model_id must be between 1 and 256 characters")

    for ordinal, chunk in enumerate(chunks):
        if chunk.ordinal != ordinal:
            raise ValueError("chunk ordinals must be consecutive and start at zero")
        if chunk.start < 0 or chunk.end <= chunk.start or chunk.end > len(normalized.text):
            raise ValueError("chunk range must be within normalized text bounds")
        if normalized.text[chunk.start : chunk.end] != chunk.text:
            raise ValueError("chunk range must match normalized text")
        _validate_sha256(chunk.content_sha256, "chunk content_sha256")
        if sha256(chunk.text.encode("utf-8")).hexdigest() != chunk.content_sha256:
            raise ValueError("chunk content hash does not match chunk text")

    for vector in vectors:
        if len(vector) != _VECTOR_DIMENSION:
            raise ValueError(f"each vector must have {_VECTOR_DIMENSION} dimensions")
        if not all(isfinite(value) for value in vector):
            raise ValueError("each vector value must be finite")
        norm = sqrt(fsum(value * value for value in vector))
        if not isfinite(norm) or norm == 0:
            raise ValueError("each vector must have a finite nonzero L2 norm")


def _legal_document_insert(source_id: str, external_id: str):
    """Build the PostgreSQL identity insert used to serialize document writers."""

    return (
        insert(LegalDocument)
        .values(
            source_id=source_id,
            external_id=external_id,
        )
        .on_conflict_do_nothing(index_elements=["source_id", "external_id"])
    )


def _result_embedding_model_id(embedding_model_id: str) -> _ResultEmbeddingModelId:
    """Preserve the current ingestion result contract's demo-model type."""

    return cast(_ResultEmbeddingModelId, embedding_model_id)


class DocumentRepository:
    """Persist immutable document snapshots in one PostgreSQL transaction.

    Database append-only behavior relies on application-role and repository discipline;
    this demo intentionally has no database triggers for update or delete prevention.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_existing(
        self,
        source_id: str,
        external_id: str,
        snapshot_sha256: str,
        *,
        block_count: int,
        embedding_model_id: str,
    ) -> IngestionResult | None:
        """Return an existing snapshot result without creating related records."""

        _validate_sha256(snapshot_sha256, "snapshot_sha256")
        if block_count < 1:
            raise ValueError("block_count must be positive")
        if not embedding_model_id or len(embedding_model_id) > 256:
            raise ValueError("embedding_model_id must be between 1 and 256 characters")

        async with self._session_factory() as session:
            version = await self._select_existing_version(
                session,
                source_id=source_id,
                external_id=external_id,
                snapshot_sha256=snapshot_sha256,
            )
            if version is None:
                return None
            return await self._existing_result(session, version, embedding_model_id)

    async def persist(
        self,
        snapshot: LegalDocumentSnapshot,
        normalized: NormalizedDocument,
        chunks: tuple[ChunkDraft, ...],
        vectors: tuple[tuple[float, ...], ...],
        *,
        snapshot_sha256: str,
        embedding_model_id: str,
        embedding_kind: EmbeddingKind,
    ) -> IngestionResult:
        """Atomically write a new immutable version unless its snapshot already exists."""

        _validate_payload(
            snapshot,
            normalized,
            chunks,
            vectors,
            snapshot_sha256,
            embedding_model_id,
        )

        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    _legal_document_insert(snapshot.source_id, snapshot.external_id)
                )
                document = await session.scalar(
                    select(LegalDocument)
                    .where(
                        LegalDocument.source_id == snapshot.source_id,
                        LegalDocument.external_id == snapshot.external_id,
                    )
                    .with_for_update()
                )
                if document is None:
                    raise RuntimeError("document identity was not available after insert")

                existing = await self._select_existing_version(
                    session,
                    source_id=snapshot.source_id,
                    external_id=snapshot.external_id,
                    snapshot_sha256=snapshot_sha256,
                )
                if existing is not None:
                    return await self._existing_result(session, existing, embedding_model_id)

                current_version_number = await session.scalar(
                    select(func.max(DocumentVersion.version_number)).where(
                        DocumentVersion.document_id == document.id
                    )
                )
                version = DocumentVersion(
                    document_id=document.id,
                    version_number=(current_version_number or 0) + 1,
                    document_number=snapshot.document_number,
                    document_number_normalized=normalize_document_number(snapshot.document_number),
                    title=snapshot.title,
                    document_type=snapshot.document_type,
                    issuing_authority=snapshot.issuing_authority,
                    issue_date=snapshot.issue_date,
                    effective_date=snapshot.effective_date,
                    source_updated_at=snapshot.source_updated_at,
                    legal_status=snapshot.legal_status,
                    canonical_url=snapshot.canonical_url,
                    raw_html=snapshot.content_html,
                    normalized_text=normalized.text,
                    snapshot_sha256=snapshot_sha256,
                    source_content_sha256=snapshot.content_sha256,
                    normalized_text_sha256=normalized.sha256,
                    normalizer_version=normalized.normalizer_version,
                    normalized_block_count=len(normalized.blocks),
                )
                session.add(version)
                await session.flush()

                trust_mode = snapshot.provenance.transport_trust_mode
                assert trust_mode is not None
                session.add(
                    SourceProvenanceRecord(
                        document_version_id=version.id,
                        provenance_type=snapshot.provenance.provenance_type.value,
                        source_id=snapshot.provenance.source_id,
                        transport=snapshot.provenance.transport,
                        operation=snapshot.provenance.operation,
                        retrieved_at=snapshot.provenance.retrieved_at,
                        canonical_url=snapshot.provenance.canonical_url,
                        tls_verified=snapshot.provenance.tls_verified,
                        transport_trust_mode=trust_mode.value,
                        tls_chain_verified=snapshot.provenance.tls_chain_verified,
                        tls_hostname_verified=snapshot.provenance.tls_hostname_verified,
                        trust_exception_id=snapshot.provenance.trust_exception_id,
                        trust_exception_digest=snapshot.provenance.trust_exception_digest,
                        policy_id=snapshot.provenance.policy_id,
                        policy_version=snapshot.provenance.policy_version,
                        compiled_policy_digest=snapshot.provenance.compiled_policy_digest,
                        registry_snapshot_digest=snapshot.provenance.registry_snapshot_digest,
                        pin_set_id=snapshot.provenance.pin_set_id,
                        pin_set_version=snapshot.provenance.pin_set_version,
                        pin_set_digest=snapshot.provenance.pin_set_digest,
                        matched_pin_id=snapshot.provenance.matched_pin_id,
                        peer_certificate_not_before=snapshot.provenance.peer_certificate_not_before,
                        peer_certificate_not_after=snapshot.provenance.peer_certificate_not_after,
                        acquisition_correlation_id=snapshot.provenance.acquisition_correlation_id,
                    )
                )

                persisted_chunks = [
                    DocumentChunk(
                        document_version_id=version.id,
                        ordinal=chunk.ordinal,
                        content_text=chunk.text,
                        start_char=chunk.start,
                        end_char=chunk.end,
                        content_sha256=chunk.content_sha256,
                        chunker_version=chunk.chunker_version,
                        locator=dict(chunk.locator) if chunk.locator is not None else None,
                    )
                    for chunk in chunks
                ]
                session.add_all(persisted_chunks)
                await session.flush()

                session.add_all(
                    ChunkEmbedding(
                        document_chunk_id=chunk.id,
                        embedding=list(vector),
                        embedding_model_id=embedding_model_id,
                        embedding_kind=embedding_kind.value,
                        dimension=_VECTOR_DIMENSION,
                        embedding_input_sha256=draft.content_sha256,
                    )
                    for chunk, draft, vector in zip(persisted_chunks, chunks, vectors, strict=True)
                )

                return IngestionResult(
                    document_id=document.id,
                    document_version_id=version.id,
                    version_number=version.version_number,
                    outcome=IngestionOutcome.CREATED,
                    block_count=len(normalized.blocks),
                    chunk_count=len(persisted_chunks),
                    embedding_count=len(vectors),
                    embedding_model_id=_result_embedding_model_id(embedding_model_id),
                    semantic_ready=False,
                )

    async def _select_existing_version(
        self,
        session: AsyncSession,
        *,
        source_id: str,
        external_id: str,
        snapshot_sha256: str,
    ) -> DocumentVersion | None:
        return await session.scalar(
            select(DocumentVersion)
            .join(DocumentVersion.document)
            .where(
                LegalDocument.source_id == source_id,
                LegalDocument.external_id == external_id,
                DocumentVersion.snapshot_sha256 == snapshot_sha256,
            )
        )

    async def _existing_result(
        self,
        session: AsyncSession,
        version: DocumentVersion,
        embedding_model_id: str,
    ) -> IngestionResult:
        chunk_count = await session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_version_id == version.id)
        )
        embedding_count = await session.scalar(
            select(func.count())
            .select_from(ChunkEmbedding)
            .join(DocumentChunk, ChunkEmbedding.document_chunk_id == DocumentChunk.id)
            .where(DocumentChunk.document_version_id == version.id)
        )
        return IngestionResult(
            document_id=version.document_id,
            document_version_id=version.id,
            version_number=version.version_number,
            outcome=IngestionOutcome.UNCHANGED,
            block_count=version.normalized_block_count,
            chunk_count=int(chunk_count or 0),
            embedding_count=int(embedding_count or 0),
            embedding_model_id=_result_embedding_model_id(embedding_model_id),
            semantic_ready=False,
        )
