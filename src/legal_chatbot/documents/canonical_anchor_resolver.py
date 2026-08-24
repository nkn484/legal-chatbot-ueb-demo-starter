"""PostgreSQL adapter for server-owned canonical document anchor resolution."""

from __future__ import annotations

import unicodedata
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import DocumentVersion, LegalDocument

MAX_ANCHOR_MENTIONS = 2
MAX_ANCHOR_MENTION_CHARS = 256
_MAX_ACTIVE_SOURCE_IDS = 3
_MAX_SOURCE_ID_CHARS = 32


def normalize_anchor_mention(value: str) -> str:
    """Apply the exact comparison normalization used by this adapter."""

    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class PostgresCanonicalAnchorResolver:
    """Resolve exact title or number anchors to latest active internal document IDs only.

    This adapter intentionally does not resolve article, clause, point, external ID, or any
    other legal metadata. It is structurally compatible with the chat-boundary
    ``CanonicalAnchorResolverPort`` without importing the chat package.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
    ) -> None:
        self._session_factory = session_factory
        self._active_source_ids = self._validate_active_source_ids(active_source_ids)

    async def resolve(self, anchor_mentions: tuple[str, ...]) -> tuple[UUID, ...] | None:
        """Return unique document IDs for all anchors, or ``None`` on any failed resolution."""

        if not anchor_mentions or len(anchor_mentions) > MAX_ANCHOR_MENTIONS:
            return None
        mentions = tuple(normalize_anchor_mention(mention) for mention in anchor_mentions)
        if any(
            not mention or len(mention) > MAX_ANCHOR_MENTION_CHARS for mention in mentions
        ) or len(set(mentions)) != len(mentions):
            return None

        latest_version_number = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        statement = (
            select(LegalDocument.id, DocumentVersion.title, DocumentVersion.document_number)
            .join(DocumentVersion, DocumentVersion.document_id == LegalDocument.id)
            .where(
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == latest_version_number,
            )
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()

        matches: dict[str, set[UUID]] = {mention: set() for mention in mentions}
        for document_id, title, document_number in rows:
            normalized_values = {
                normalize_anchor_mention(value)
                for value in (title, document_number)
                if value is not None
            }
            for mention in mentions:
                if mention in normalized_values:
                    matches[mention].add(document_id)

        resolved_by_mention: list[UUID] = []
        for mention in mentions:
            document_ids = matches[mention]
            if len(document_ids) != 1:
                return None
            resolved_by_mention.append(next(iter(document_ids)))
        return tuple(dict.fromkeys(resolved_by_mention))

    @staticmethod
    def _validate_active_source_ids(active_source_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Require the same explicit immutable active-source contract as retrieval."""

        if (
            not isinstance(active_source_ids, tuple)
            or not 1 <= len(active_source_ids) <= _MAX_ACTIVE_SOURCE_IDS
        ):
            raise ValueError("active_source_ids must be a nonempty bounded tuple")
        if any(
            not isinstance(source_id, str)
            or not source_id
            or source_id != source_id.strip()
            or len(source_id) > _MAX_SOURCE_ID_CHARS
            for source_id in active_source_ids
        ):
            raise ValueError("active_source_ids must contain bounded nonblank IDs")
        if len(set(active_source_ids)) != len(active_source_ids):
            raise ValueError("active_source_ids must be unique")
        return active_source_ids
