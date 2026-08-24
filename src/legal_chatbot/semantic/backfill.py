"""Offline semantic embedding backfill orchestration without runtime integration."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from legal_chatbot.documents.semantic_embedding_repository import (
    PendingSemanticChunk,
    SemanticEmbeddingRepository,
    SemanticEmbeddingWrite,
)
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode
from legal_chatbot.semantic.ports import SemanticEmbeddingPort


@dataclass(frozen=True)
class SemanticBackfillProgress:
    """Content-free incremental counts for an explicit source scope."""

    source_counts: dict[str, int]
    inserted: int


@dataclass(frozen=True)
class SemanticBackfillResult:
    """Content-free terminal result; nonzero failures leave work uninserted."""

    inserted: int
    coverage: dict[str, tuple[int, int]]


ProgressCallback = Callable[[SemanticBackfillProgress], Awaitable[None] | None]


class SemanticBackfillService:
    """Embed outside transactions, then append only still-missing semantic rows."""

    def __init__(
        self,
        repository: SemanticEmbeddingRepository,
        embedder: SemanticEmbeddingPort,
        *,
        batch_size: int,
    ) -> None:
        if not 1 <= batch_size <= 64:
            raise ValueError("batch_size must be between 1 and 64")
        self._repository = repository
        self._embedder = embedder
        self._batch_size = batch_size

    async def run(self, progress: ProgressCallback | None = None) -> SemanticBackfillResult:
        """Process all keyset batches; exceptions intentionally leave remaining rows missing."""

        cursor: UUID | None = None
        inserted = 0
        while True:
            pending = await self._repository.fetch_missing_batch(
                after_chunk_id=cursor, batch_size=self._batch_size
            )
            if not pending:
                break
            cursor = pending[-1].chunk_id
            batch = await self._embedder.embed_documents(
                tuple(item.content_text for item in pending)
            )
            if len(batch.vectors) != len(pending):
                raise SemanticError(SemanticErrorCode.INVALID_VECTOR)
            writes = self._writes(pending, batch.vectors)
            batch_inserted = await self._repository.insert_missing(writes)
            inserted += batch_inserted
            if progress is not None:
                source_counts = dict(Counter(item.source_id for item in pending))
                emitted = progress(SemanticBackfillProgress(source_counts, batch_inserted))
                if emitted is not None:
                    await emitted
        return SemanticBackfillResult(inserted=inserted, coverage=await self._repository.coverage())

    @staticmethod
    def _writes(
        pending: tuple[PendingSemanticChunk, ...], vectors: tuple[tuple[float, ...], ...]
    ) -> tuple[SemanticEmbeddingWrite, ...]:
        return tuple(
            SemanticEmbeddingWrite(
                chunk_id=item.chunk_id,
                content_text=item.content_text,
                vector=vector,
            )
            for item, vector in zip(pending, vectors, strict=True)
        )
