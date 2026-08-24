"""PostgreSQL boundary for append-only offline semantic embedding backfill."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import fsum, isfinite, sqrt
from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.semantic.constants import PASSAGE_PREFIX, SEMANTIC_DIMENSION, SEMANTIC_PROFILE_ID
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode

_MAX_ACTIVE_SOURCE_IDS = 3
_MAX_SOURCE_ID_CHARS = 32


@dataclass(frozen=True)
class PendingSemanticChunk:
    """A short-lived eligible chunk projection; its text must not be logged or persisted here."""

    chunk_id: UUID
    source_id: str
    content_text: str


@dataclass(frozen=True)
class SemanticEmbeddingWrite:
    """One validated vector to append for an already selected chunk."""

    chunk_id: UUID
    content_text: str
    vector: tuple[float, ...]


def semantic_embedding_input_sha256(content_text: str) -> str:
    """Bind the stored vector to the exact E5-prefixed passage input."""

    return sha256((PASSAGE_PREFIX + content_text).encode("utf-8")).hexdigest()


class SemanticEmbeddingRepository:
    """Fetch current trusted chunks and append only missing exact-profile rows."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
    ) -> None:
        self._session_factory = session_factory
        self._active_source_ids = self._validate_active_source_ids(active_source_ids)

    async def fetch_missing_batch(
        self, *, after_chunk_id: UUID | None, batch_size: int
    ) -> tuple[PendingSemanticChunk, ...]:
        """Read one keyset batch of latest, strict-trust chunks lacking this semantic row."""

        if not 1 <= batch_size <= 64:
            raise ValueError("batch_size must be between 1 and 64")
        latest_version_number = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        eligible_provenance = exists(
            select(SourceProvenanceRecord.id).where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                or_(
                    SourceProvenanceRecord.provenance_type == "source_fetch",
                    and_(
                        SourceProvenanceRecord.provenance_type == "manual_snapshot",
                        SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                    ),
                ),
            )
        )
        missing_semantic_row = ~exists(
            select(ChunkEmbedding.id).where(
                ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
            )
        )
        predicates = [
            LegalDocument.source_id.in_(self._active_source_ids),
            DocumentVersion.version_number == latest_version_number,
            eligible_provenance,
            missing_semantic_row,
        ]
        if after_chunk_id is not None:
            predicates.append(DocumentChunk.id > after_chunk_id)
        statement = (
            select(DocumentChunk.id, LegalDocument.source_id, DocumentChunk.content_text)
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .where(*predicates)
            .order_by(DocumentChunk.id.asc())
            .limit(batch_size)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple(PendingSemanticChunk(row[0], row[1], row[2]) for row in rows)

    async def insert_missing(self, rows: tuple[SemanticEmbeddingWrite, ...]) -> int:
        """Idempotently append semantic vectors in a short transaction after embedding."""

        if not rows:
            return 0
        values = [self._validated_insert_value(row) for row in rows]
        statement = (
            insert(ChunkEmbedding)
            .values(values)
            .on_conflict_do_nothing(
                index_elements=["document_chunk_id", "embedding_model_id"]
            )
        )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    result = await session.execute(statement)
                    return int(cast(object, result).rowcount or 0)  # type: ignore[attr-defined]
        except SemanticError:
            raise
        except Exception as error:
            raise SemanticError(SemanticErrorCode.PERSISTENCE_FAILURE) from error

    async def coverage(self) -> dict[str, tuple[int, int]]:
        """Return content-free eligible and ready counts by explicit source."""

        latest_version_number = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        eligible_provenance = exists(
            select(SourceProvenanceRecord.id).where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                SourceProvenanceRecord.provenance_type.in_(("source_fetch", "manual_snapshot")),
            )
        )
        statement = (
            select(
                LegalDocument.source_id,
                func.count(DocumentChunk.id),
                func.count(ChunkEmbedding.id),
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .outerjoin(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
                ),
            )
            .where(
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == latest_version_number,
                eligible_provenance,
            )
            .group_by(LegalDocument.source_id)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        result = {source_id: (0, 0) for source_id in self._active_source_ids}
        result.update({row[0]: (int(row[1]), int(row[2])) for row in rows})
        return result

    @staticmethod
    def _validated_insert_value(row: SemanticEmbeddingWrite) -> dict[str, object]:
        if not isinstance(row.content_text, str) or not row.content_text.strip():
            raise SemanticError(SemanticErrorCode.INVALID_INPUT)
        if len(row.vector) != SEMANTIC_DIMENSION or not all(
            isfinite(value) for value in row.vector
        ):
            raise SemanticError(SemanticErrorCode.INVALID_VECTOR)
        norm = sqrt(fsum(value * value for value in row.vector))
        if not isfinite(norm) or norm == 0 or abs(norm - 1.0) > 1e-4:
            raise SemanticError(SemanticErrorCode.INVALID_VECTOR)
        return {
            "document_chunk_id": row.chunk_id,
            "embedding": list(row.vector),
            "embedding_model_id": SEMANTIC_PROFILE_ID,
            "embedding_kind": "semantic",
            "dimension": SEMANTIC_DIMENSION,
            "embedding_input_sha256": semantic_embedding_input_sha256(row.content_text),
        }

    @staticmethod
    def _validate_active_source_ids(active_source_ids: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not isinstance(active_source_ids, tuple)
            or not 1 <= len(active_source_ids) <= _MAX_ACTIVE_SOURCE_IDS
            or len(set(active_source_ids)) != len(active_source_ids)
            or any(
                not isinstance(source_id, str)
                or not source_id
                or source_id != source_id.strip()
                or len(source_id) > _MAX_SOURCE_ID_CHARS
                for source_id in active_source_ids
            )
        ):
            raise ValueError("active_source_ids must be a unique nonempty bounded tuple")
        return active_source_ids
