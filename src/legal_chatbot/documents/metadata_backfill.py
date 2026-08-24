"""Offline idempotent backfill for derived document-number metadata keys."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from legal_chatbot.documents.metadata_normalization import normalize_document_number
from legal_chatbot.documents.orm import DocumentVersion

_MAX_BATCH_SIZE = 500


@dataclass(frozen=True)
class MetadataBackfillResult:
    """Content-free completion counts for the derived-column-only operation."""

    scanned: int
    updated: int


class DocumentMetadataBackfill:
    """Fill missing canonical number keys with bounded short transactions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def run(self, *, batch_size: int = _MAX_BATCH_SIZE) -> MetadataBackfillResult:
        if not 1 <= batch_size <= _MAX_BATCH_SIZE:
            raise ValueError("batch_size must be between 1 and 500")
        cursor: UUID | None = None
        scanned = updated = 0
        while True:
            batch = await self._next_batch(cursor, batch_size)
            if not batch:
                break
            cursor = batch[-1][0]
            scanned += len(batch)
            async with self._session_factory() as session:
                async with session.begin():
                    for version_id, document_number in batch:
                        normalized = normalize_document_number(document_number)
                        if normalized is None:
                            continue
                        result = await session.execute(
                            update(DocumentVersion)
                            .where(
                                DocumentVersion.id == version_id,
                                DocumentVersion.document_number_normalized.is_(None),
                            )
                            .values(document_number_normalized=normalized)
                        )
                        updated += int(getattr(result, "rowcount", 0) or 0)
        return MetadataBackfillResult(scanned=scanned, updated=updated)

    async def _next_batch(
        self, cursor: UUID | None, batch_size: int
    ) -> tuple[tuple[UUID, str], ...]:
        predicates: list[ColumnElement[bool]] = [
            DocumentVersion.document_number.is_not(None),
            DocumentVersion.document_number_normalized.is_(None),
        ]
        if cursor is not None:
            predicates.append(DocumentVersion.id > cursor)
        statement = (
            select(DocumentVersion.id, DocumentVersion.document_number)
            .where(*predicates)
            .order_by(DocumentVersion.id.asc())
            .limit(batch_size)
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return tuple((row[0], row[1]) for row in rows if row[1] is not None)
