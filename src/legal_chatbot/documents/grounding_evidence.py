"""Read-only PostgreSQL adapter for grounded-chat evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.chat.errors import ChatError, ChatErrorCode
from legal_chatbot.chat.models import GroundingEvidence, GroundingEvidenceRequest, GroundingExcerpt
from legal_chatbot.chat.port import GroundingEvidencePort
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalScope,
    RetrievalTrustScope,
    coerce_provenance_type,
    coerce_transport_trust_mode,
    evidence_trust_label_for,
    is_evidence_provenance_eligible,
)


class _GroundingSettings(Protocol):
    """The narrow settings surface needed by this read boundary."""

    max_citations: int
    excerpt_max_chars: int
    total_evidence_max_chars: int


class PostgresGroundingEvidenceAdapter(GroundingEvidencePort):
    """Load exact retrieval-run citations and bounded untrusted chunk excerpts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: _GroundingSettings,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def load(self, request: GroundingEvidenceRequest) -> GroundingEvidence:
        """Return all requested evidence or a normalized grounding failure."""

        try:
            self._validate_request_bounds(request)
            async with self._session_factory() as session:
                rows = await self._select_rows(session, request)
            ordered_rows = self._in_caller_order(rows, request)
            excerpts = self._bounded_excerpts(ordered_rows)
            return GroundingEvidence(retrieval_run_id=request.retrieval_run_id, excerpts=excerpts)
        except ChatError:
            raise
        except Exception:
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE) from None

    def _validate_request_bounds(self, request: GroundingEvidenceRequest) -> None:
        citation_count = len(request.citation_ids)
        if (
            citation_count > self._settings.max_citations
            or self._settings.total_evidence_max_chars < citation_count
        ):
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE)

    async def _select_rows(
        self, session: AsyncSession, request: GroundingEvidenceRequest
    ) -> tuple[_GroundingRow, ...]:
        """Issue the adapter's sole SQL statement using only the evidence projection."""

        statement = (
            select(
                CitationRecord.id,
                CitationRecord.retrieval_run_id,
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                DocumentVersion.id,
                DocumentVersion.document_id,
                SourceProvenanceRecord.id,
                SourceProvenanceRecord.source_id,
                LegalDocument.external_id,
                DocumentVersion.document_number,
                DocumentVersion.title,
                DocumentVersion.canonical_url,
                DocumentChunk.locator,
                DocumentChunk.content_text,
                RetrievalRun.trust_scope,
                SourceProvenanceRecord.provenance_type,
                SourceProvenanceRecord.transport_trust_mode,
            )
            .select_from(CitationRecord)
            .join(RetrievalRun, CitationRecord.retrieval_run_id == RetrievalRun.id)
            .join(DocumentChunk, CitationRecord.document_chunk_id == DocumentChunk.id)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                SourceProvenanceRecord,
                and_(
                    CitationRecord.source_provenance_record_id == SourceProvenanceRecord.id,
                    SourceProvenanceRecord.document_version_id == DocumentChunk.document_version_id,
                ),
            )
            .where(
                CitationRecord.retrieval_run_id == request.retrieval_run_id,
                CitationRecord.id.in_(request.citation_ids),
                RetrievalRun.scope == RetrievalScope.LATEST_INGESTED.value,
            )
        )
        result = await session.execute(statement)
        return tuple(_GroundingRow(*tuple(row)) for row in result.all())

    @staticmethod
    def _in_caller_order(
        rows: tuple[_GroundingRow, ...], request: GroundingEvidenceRequest
    ) -> tuple[_GroundingRow, ...]:
        by_citation_id = {row.citation_id: row for row in rows}
        requested_ids = set(request.citation_ids)
        if (
            len(by_citation_id) != len(rows)
            or set(by_citation_id) != requested_ids
            or any(row.retrieval_run_id != request.retrieval_run_id for row in rows)
            or any(not row.has_eligible_transport_trust() for row in rows)
        ):
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE)
        return tuple(by_citation_id[citation_id] for citation_id in request.citation_ids)

    def _bounded_excerpts(self, rows: tuple[_GroundingRow, ...]) -> tuple[GroundingExcerpt, ...]:
        normalized_texts = tuple(row.content_text.strip() for row in rows)
        if any(not text for text in normalized_texts):
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE)

        lengths = self._fair_lengths(normalized_texts)
        return tuple(
            GroundingExcerpt(citation=row.resolved_citation(), text=text[:length])
            for row, text, length in zip(rows, normalized_texts, lengths, strict=True)
        )

    def _fair_lengths(self, texts: tuple[str, ...]) -> tuple[int, ...]:
        capacities = [min(len(text), self._settings.excerpt_max_chars) for text in texts]
        if any(capacity < 1 for capacity in capacities):
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE)

        remaining = min(self._settings.total_evidence_max_chars, sum(capacities))
        lengths = [0] * len(capacities)
        while remaining:
            progressed = False
            for index, capacity in enumerate(capacities):
                if remaining and lengths[index] < capacity:
                    lengths[index] += 1
                    remaining -= 1
                    progressed = True
            if not progressed:
                break
        if any(length < 1 for length in lengths):
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE)
        return tuple(lengths)


@dataclass(frozen=True)
class _GroundingRow:
    """The nullable-free result of the evidence join, held only in memory."""

    citation_id: UUID
    retrieval_run_id: UUID
    document_chunk_id: UUID
    document_version_id: UUID
    version_id: UUID
    document_id: UUID
    source_provenance_record_id: UUID
    source_id: str
    external_id: str
    document_number: str | None
    title: str | None
    canonical_url: str | None
    locator: dict[str, object] | None
    content_text: str
    trust_scope: str = RetrievalTrustScope.STRICT_TLS_ONLY.value
    provenance_type: str = "source_fetch"
    transport_trust_mode: str = "STRICT_TLS"

    def has_eligible_transport_trust(self) -> bool:
        """Validate persisted run/provenance trust rather than trusting the join alone."""

        try:
            return is_evidence_provenance_eligible(
                RetrievalTrustScope(self.trust_scope),
                coerce_transport_trust_mode(self.transport_trust_mode),
                coerce_provenance_type(self.provenance_type),
            )
        except ValueError:
            return False

    def resolved_citation(self) -> ResolvedCitation:
        """Discard the excerpt before exposing persisted citation metadata."""

        if self.version_id != self.document_version_id or not self.has_eligible_transport_trust():
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE)
        try:
            transport_trust_mode = coerce_transport_trust_mode(self.transport_trust_mode)
            provenance_type = coerce_provenance_type(self.provenance_type)
            evidence_trust_label = evidence_trust_label_for(transport_trust_mode, provenance_type)
        except ValueError:
            raise ChatError(ChatErrorCode.GROUNDING_FAILURE) from None
        return ResolvedCitation(
            citation_id=self.citation_id,
            retrieval_run_id=self.retrieval_run_id,
            document_chunk_id=self.document_chunk_id,
            document_version_id=self.document_version_id,
            document_id=self.document_id,
            source_provenance_record_id=self.source_provenance_record_id,
            provenance_type=provenance_type,
            transport_trust_mode=transport_trust_mode,
            evidence_trust_label=evidence_trust_label,
            source_id=self.source_id,
            external_id=self.external_id,
            document_number=self.document_number,
            title=self.title,
            canonical_url=self.canonical_url,
            locator=self.locator,
        )
