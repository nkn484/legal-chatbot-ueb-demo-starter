"""Read-only PostgreSQL adapters for the P1-P10 vertical-slice profile.

The adapters retain exact document/version/provenance identities.  They do not
write retrieval state, use benchmark data, or make authority conclusions.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import (
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.quality_candidate_reader import PostgresQualityCandidateReader
from legal_chatbot.legal_evidence.authority import AuthorityMetadata
from legal_chatbot.legal_evidence.composition import CompositionEvidence
from legal_chatbot.legal_evidence.discovery import (
    DiscoveryLane,
    DiscoveryLaneObservation,
    DiscoveryReadRequest,
    RawDiscoveryCandidate,
)
from legal_chatbot.legal_evidence.models import (
    AuthorityRole,
    AuthorityState,
    DocumentVersionReference,
    EvidenceReference,
    EvidenceUnit,
)
from legal_chatbot.legal_evidence.pinpoint import PinpointReadRequest, RawPinpointEvidence
from legal_chatbot.legal_evidence.repair import TargetedRepairRequest
from legal_chatbot.retrieval.quality_repair.models import RetrievalLane
from legal_chatbot.semantic.ports import SemanticEmbeddingPort

_STRICT_PROVENANCE_TYPES = ("source_fetch", "manual_snapshot")
_REVOKED_STATUS_MARKERS = ("repeal", "revok", "het hieu luc", "hết hiệu lực")


class AuthorityMetadataReaderPort(Protocol):
    """Load deterministic P4 filter inputs for exact P3 candidate identities."""

    async def load(
        self, candidates: Sequence[object]
    ) -> tuple[AuthorityMetadata, ...]: ...


@dataclass(frozen=True)
class P3ReadTelemetry:
    """Count-only per-request P3 telemetry used by the diagnostic runner."""

    title_lane_count: int
    content_fts_lane_count: int
    semantic_lane_count: int


class PostgresBroadDiscoveryReader:
    """Adapt the real three-lane PostgreSQL reader to P3 raw candidates."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        semantic_embedder: SemanticEmbeddingPort,
        active_source_ids: tuple[str, ...],
    ) -> None:
        self._reader = PostgresQualityCandidateReader(session_factory)
        self._semantic_embedder = semantic_embedder
        self._active_source_ids = active_source_ids

    async def discover(self, request: DiscoveryReadRequest) -> tuple[RawDiscoveryCandidate, ...]:
        embedded = await self._semantic_embedder.embed_query(request.query_text)
        if len(embedded.vectors) != 1:
            raise RuntimeError("P3_SEMANTIC_QUERY_VECTOR_INVALID")
        result = await self._reader.read_candidates(
            request.query_text,
            self._active_source_ids,
            embedded.vectors[0],
            diagnostic_limit=30,
        )
        raw: list[RawDiscoveryCandidate] = []
        for lane, candidates in result.lane_candidates.items():
            mapped_lane = self._discovery_lane(lane)
            for candidate in candidates:
                identity = candidate.identity
                document = DocumentVersionReference(
                    document_id=identity.document_id,
                    document_version_id=identity.document_version_id,
                    provenance_record_id=identity.provenance_record_id,
                    source_id=identity.source_id.value,
                )
                observation = candidate.observations[0]
                raw.append(
                    RawDiscoveryCandidate(
                        document=document,
                        state=(
                            AuthorityState.ELIGIBLE
                            if candidate.eligible
                            else AuthorityState.FILTERED_PROVENANCE
                        ),
                        provenance_verified=(
                            identity.transport_trust_mode.value == "STRICT_TLS"
                            and identity.provenance_type.value in _STRICT_PROVENANCE_TYPES
                        ),
                        matched_sub_intent_ids=(request.sub_intent_id,),
                        observations=(
                            DiscoveryLaneObservation(
                                lane=mapped_lane,
                                rank=observation.rank,
                                score=observation.score,
                                query_count=observation.query_count,
                                elapsed_ms=observation.elapsed_ms,
                            ),
                        ),
                    )
                )
        return tuple(raw)

    @staticmethod
    def _discovery_lane(lane: RetrievalLane) -> DiscoveryLane:
        mapping = {
            RetrievalLane.SEMANTIC: DiscoveryLane.SEMANTIC_VECTOR,
            RetrievalLane.CONTENT_FTS: DiscoveryLane.CONTENT_FTS,
            RetrievalLane.TITLE_FTS: DiscoveryLane.TITLE_METADATA,
        }
        return mapping[lane]


class PostgresAuthorityMetadataReader:
    """Read deterministic P4 filter inputs for the exact P3 discovery workspace."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load(self, candidates: Sequence[object]) -> tuple[AuthorityMetadata, ...]:
        if not candidates:
            return ()
        candidate_documents = tuple(candidate.document for candidate in candidates)
        versions = tuple(item.document_version_id for item in candidate_documents)
        provenance_ids = tuple(item.provenance_record_id for item in candidate_documents)
        statement = (
            select(
                DocumentVersion.id,
                DocumentVersion.document_id,
                LegalDocument.source_id,
                DocumentVersion.legal_status,
                DocumentVersion.title,
                DocumentVersion.document_type,
                DocumentVersion.issuing_authority,
                SourceProvenanceRecord.id,
                SourceProvenanceRecord.provenance_type,
                SourceProvenanceRecord.transport_trust_mode,
            )
            .select_from(DocumentVersion)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                SourceProvenanceRecord,
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
            )
            .where(
                DocumentVersion.id.in_(versions),
                SourceProvenanceRecord.id.in_(provenance_ids),
            )
        )
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                rows = tuple((await session.execute(statement)).all())
        by_identity = {
            (row[0], row[7]): row
            for row in rows
        }
        result: list[AuthorityMetadata] = []
        for candidate in candidates:
            document = candidate.document
            row = by_identity.get((document.document_version_id, document.provenance_record_id))
            provenance_valid = bool(
                row
                and row[1] == document.document_id
                and row[2] == document.source_id
                and row[8] in _STRICT_PROVENANCE_TYPES
                and row[9] == "STRICT_TLS"
            )
            status = "" if row is None or row[3] is None else row[3].casefold()
            status_eligible = provenance_valid and not any(
                marker in status for marker in _REVOKED_STATUS_MARKERS
            )
            result.append(
                AuthorityMetadata(
                    document=document,
                    discovery_state=candidate.state,
                    provenance_valid=provenance_valid,
                    # The adapter only establishes absence of an explicit catalog conflict.
                    scope_compatible=True,
                    source_binding_compatible=provenance_valid,
                    status_eligible=status_eligible,
                    status_metadata_current=bool(status and "current" in status),
                    matched_sub_intent_ids=candidate.matched_sub_intent_ids,
                    catalog_state=candidate.state,
                    title=None if row is None else row[4],
                    document_type=None if row is None else row[5],
                    issuing_authority=None if row is None else row[6],
                )
            )
        return tuple(result)


class PostgresPinpointEvidenceReader:
    """Read focused evidence only from the P5-approved version/provenance pairs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def read(self, request: PinpointReadRequest) -> tuple[RawPinpointEvidence, ...]:
        rows = await self._focused_rows(request.documents, request.query_text)
        by_version = {item.document_version_id: item for item in request.documents}
        return tuple(
            RawPinpointEvidence(
                evidence=EvidenceReference(
                    document=by_version[row[1]],
                    chunk_id=row[0],
                    locator=self._locator(row[2], row[3]),
                ),
                sub_intent_id=request.sub_intent_id,
                authority_role=AuthorityRole.BACKGROUND,
                rank=index,
            )
            for index, row in enumerate(rows, start=1)
        )

    async def _focused_rows(
        self,
        documents: tuple[DocumentVersionReference, ...],
        query_text: str,
    ) -> tuple[tuple[UUID, UUID, int, object], ...]:
        version_ids = tuple(item.document_version_id for item in documents)
        provenance_ids = tuple(item.provenance_record_id for item in documents)
        query = func.websearch_to_tsquery(text("'pg_catalog.simple'::regconfig"), query_text)
        score = func.ts_rank_cd(DocumentChunk.search_vector, query)
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                DocumentChunk.ordinal,
                DocumentChunk.locator,
                score.label("score"),
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                SourceProvenanceRecord,
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
            )
            .where(
                DocumentVersion.id.in_(version_ids),
                SourceProvenanceRecord.id.in_(provenance_ids),
                SourceProvenanceRecord.source_id == LegalDocument.source_id,
                SourceProvenanceRecord.provenance_type.in_(_STRICT_PROVENANCE_TYPES),
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                DocumentChunk.search_vector.op("@@")(query),
            )
            .order_by(score.desc(), DocumentChunk.id.asc())
            .limit(50)
        )
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                result = await session.execute(statement)
                return tuple((row[0], row[1], row[2], row[3]) for row in result.all())

    @staticmethod
    def _locator(ordinal: int, persisted_locator: object) -> str:
        if isinstance(persisted_locator, dict):
            encoded = json.dumps(persisted_locator, ensure_ascii=True, sort_keys=True)
            if 1 <= len(encoded) <= 480:
                return encoded
        return f"chunk:{ordinal}"


class PostgresTargetedRepairReader:
    """Run the one P8 targeted read against only P5-approved authority documents."""

    def __init__(self, pinpoint_reader: PostgresPinpointEvidenceReader) -> None:
        self._pinpoint_reader = pinpoint_reader

    async def repair(self, request: TargetedRepairRequest) -> tuple[EvidenceUnit, ...]:
        pinpoint = PinpointReadRequest(
            sub_intent_id=request.sub_intent_id,
            document_version_ids=tuple(item.document_version_id for item in request.documents),
            documents=request.documents,
            query_text=request.query_text,
        )
        rows = await self._pinpoint_reader.read(pinpoint)
        role_by_version = dict(zip(
            (item.document_version_id for item in request.documents),
            request.authority_roles,
            strict=True,
        ))
        return tuple(
            EvidenceUnit(
                evidence=row.evidence,
                supported_sub_intent_ids=(request.sub_intent_id,),
                authority_role=role_by_version[row.evidence.document.document_version_id],
            )
            for row in rows[:5]
        )


class PostgresCompositionEvidenceReader:
    """Load exact selected evidence excerpts without creating a retrieval side path."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], excerpt_max_chars: int = 1_600
    ) -> None:
        self._session_factory = session_factory
        self._excerpt_max_chars = excerpt_max_chars

    async def load(self, evidence_units: Sequence[EvidenceUnit]) -> tuple[CompositionEvidence, ...]:
        if not evidence_units:
            return ()
        chunk_ids = tuple(unit.evidence.chunk_id for unit in evidence_units)
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                DocumentChunk.content_text,
                SourceProvenanceRecord.id,
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                SourceProvenanceRecord,
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
            )
            .where(
                DocumentChunk.id.in_(chunk_ids),
                SourceProvenanceRecord.provenance_type.in_(_STRICT_PROVENANCE_TYPES),
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                SourceProvenanceRecord.source_id == LegalDocument.source_id,
            )
        )
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION READ ONLY"))
                rows = tuple((await session.execute(statement)).all())
        by_chunk_provenance = {(row[0], row[3]): row for row in rows}
        loaded: list[CompositionEvidence] = []
        for unit in evidence_units:
            row = by_chunk_provenance.get(
                (unit.evidence.chunk_id, unit.evidence.document.provenance_record_id)
            )
            if (
                row is None
                or row[1] != unit.evidence.document.document_version_id
                or not row[2].strip()
            ):
                raise ValueError("selected evidence cannot be resolved with exact provenance")
            loaded.append(
                CompositionEvidence(unit=unit, excerpt=row[2].strip()[: self._excerpt_max_chars])
            )
        return tuple(loaded)


__all__ = [
    "AuthorityMetadataReaderPort",
    "P3ReadTelemetry",
    "PostgresAuthorityMetadataReader",
    "PostgresBroadDiscoveryReader",
    "PostgresCompositionEvidenceReader",
    "PostgresPinpointEvidenceReader",
    "PostgresTargetedRepairReader",
]
