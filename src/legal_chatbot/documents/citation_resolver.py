"""PostgreSQL citation-resolution adapter."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.core.logging import get_logger
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalScope,
    RetrievalTrustScope,
    coerce_transport_trust_mode,
    evidence_trust_label_for,
    is_evidence_provenance_eligible,
)
from legal_chatbot.sources.models import ProvenanceType


class PostgresCitationResolver:
    """Resolve persisted citation metadata while rejecting broken evidence links."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._logger = get_logger()

    async def resolve(self, citation_id: UUID, expected_retrieval_run_id: UUID) -> ResolvedCitation:
        """Resolve one citation from its original retrieval snapshot, not today's latest version."""

        try:
            async with self._session_factory() as session:
                row = await self._select_citation(session, citation_id)
                if row is None:
                    raise RetrievalError(RetrievalErrorCode.CITATION_NOT_FOUND)
                if row.retrieval_run_id != expected_retrieval_run_id:
                    raise RetrievalError(RetrievalErrorCode.CITATION_RUN_MISMATCH)
                if not self._has_valid_chain(row):
                    raise RetrievalError(RetrievalErrorCode.INVALID_EVIDENCE_CHAIN)
                transport_trust_mode = coerce_transport_trust_mode(row.transport_trust_mode)
                provenance_type = ProvenanceType(row.provenance_type)
                result = ResolvedCitation(
                    citation_id=row.citation_id,
                    retrieval_run_id=row.retrieval_run_id,
                    document_chunk_id=cast(UUID, row.document_chunk_id),
                    document_version_id=cast(UUID, row.document_version_id),
                    document_id=cast(UUID, row.document_id),
                    source_provenance_record_id=cast(UUID, row.source_provenance_record_id),
                    provenance_type=provenance_type,
                    transport_trust_mode=transport_trust_mode,
                    evidence_trust_label=evidence_trust_label_for(
                        transport_trust_mode, provenance_type
                    ),
                    source_id=cast(str, row.source_id),
                    external_id=cast(str, row.external_id),
                    document_number=row.document_number,
                    title=row.title,
                    canonical_url=row.canonical_url,
                    locator=row.locator,
                )
        except RetrievalError as error:
            self._log_failure(citation_id, expected_retrieval_run_id, error.code)
            raise
        except Exception:
            error = RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE)
            self._log_failure(citation_id, expected_retrieval_run_id, error.code)
            raise error from None

        self._logger.info(
            "citation_resolved",
            extra={
                "retrieval_run_id": str(result.retrieval_run_id),
                "citation_id": str(result.citation_id),
            },
        )
        return result

    async def _select_citation(
        self, session: AsyncSession, citation_id: UUID
    ) -> _CitationRow | None:
        statement = (
            select(
                CitationRecord.id,
                CitationRecord.retrieval_run_id,
                RetrievalRun.scope,
                RetrievalRun.trust_scope,
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                DocumentVersion.id,
                DocumentVersion.document_id,
                SourceProvenanceRecord.id,
                SourceProvenanceRecord.document_version_id,
                SourceProvenanceRecord.source_id,
                SourceProvenanceRecord.transport_trust_mode,
                LegalDocument.external_id,
                DocumentVersion.document_number,
                DocumentVersion.title,
                DocumentVersion.canonical_url,
                DocumentChunk.locator,
                SourceProvenanceRecord.provenance_type,
            )
            .select_from(CitationRecord)
            .join(RetrievalRun, CitationRecord.retrieval_run_id == RetrievalRun.id)
            .outerjoin(DocumentChunk, CitationRecord.document_chunk_id == DocumentChunk.id)
            .outerjoin(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .outerjoin(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .outerjoin(
                SourceProvenanceRecord,
                CitationRecord.source_provenance_record_id == SourceProvenanceRecord.id,
            )
            .where(CitationRecord.id == citation_id)
        )
        row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        return _CitationRow(*row)

    @staticmethod
    def _has_valid_chain(row: _CitationRow) -> bool:
        return (
            row.scope == RetrievalScope.LATEST_INGESTED.value
            and PostgresCitationResolver._has_eligible_transport_trust(row)
            and row.document_chunk_id is not None
            and row.document_version_id is not None
            and row.version_id == row.document_version_id
            and row.document_id is not None
            and row.source_provenance_record_id is not None
            and row.source_provenance_document_version_id == row.document_version_id
            and row.source_id is not None
            and row.external_id is not None
        )

    @staticmethod
    def _has_eligible_transport_trust(row: _CitationRow) -> bool:
        """Require the cited provenance to remain inside the persisted run's envelope."""

        try:
            return is_evidence_provenance_eligible(
                RetrievalTrustScope(row.trust_scope),
                coerce_transport_trust_mode(row.transport_trust_mode),
                ProvenanceType(row.provenance_type),
            )
        except ValueError:
            return False

    def _log_failure(
        self,
        citation_id: UUID,
        retrieval_run_id: UUID,
        code: RetrievalErrorCode,
    ) -> None:
        self._logger.warning(
            "citation_resolution_failed",
            extra={
                "retrieval_run_id": str(retrieval_run_id),
                "citation_id": str(citation_id),
                "retrieval_error_code": code.value,
            },
        )


class _CitationRow:
    """Private nullable SQL projection retained only until evidence validation completes."""

    def __init__(
        self,
        citation_id: UUID,
        retrieval_run_id: UUID,
        scope: str,
        trust_scope: str,
        document_chunk_id: UUID | None,
        document_version_id: UUID | None,
        version_id: UUID | None,
        document_id: UUID | None,
        source_provenance_record_id: UUID | None,
        source_provenance_document_version_id: UUID | None,
        source_id: str | None,
        transport_trust_mode: str,
        external_id: str | None,
        document_number: str | None,
        title: str | None,
        canonical_url: str | None,
        locator: dict[str, object] | None,
        provenance_type: str = ProvenanceType.SOURCE_FETCH.value,
    ) -> None:
        self.citation_id = citation_id
        self.retrieval_run_id = retrieval_run_id
        self.scope = scope
        self.trust_scope = trust_scope
        self.document_chunk_id = document_chunk_id
        self.document_version_id = document_version_id
        self.version_id = version_id
        self.document_id = document_id
        self.source_provenance_record_id = source_provenance_record_id
        self.source_provenance_document_version_id = source_provenance_document_version_id
        self.source_id = source_id
        self.transport_trust_mode = transport_trust_mode
        self.external_id = external_id
        self.document_number = document_number
        self.title = title
        self.canonical_url = canonical_url
        self.locator = locator
        self.provenance_type = provenance_type
