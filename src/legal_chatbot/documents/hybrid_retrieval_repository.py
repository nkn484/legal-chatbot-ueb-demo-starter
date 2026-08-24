"""Exact offline semantic and hybrid PostgreSQL retrieval adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import and_, bindparam, exists, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    QUERY_MAX_CHARS,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScope,
)
from legal_chatbot.semantic.constants import SEMANTIC_DIMENSION, SEMANTIC_PROFILE_ID
from legal_chatbot.semantic.errors import SemanticError
from legal_chatbot.semantic.models import SemanticEmbeddingBatch
from legal_chatbot.semantic.ports import SemanticEmbeddingPort

HybridRetrievalMode = Literal["semantic", "hybrid"]
_RRF_K = 60
_MAX_SOURCES = 3


@dataclass(frozen=True)
class _Candidate:
    chunk_id: UUID
    version_id: UUID
    provenance_id: UUID | None
    provenance_version_id: UUID | None
    lexical_score: float | None = None
    semantic_score: float | None = None
    reranker_score: float | None = None


class PostgresHybridRetrievalRepository:
    """Persist exact semantic-only or 1:1 raw-lexical/semantic evidence in one run."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
        embedder: SemanticEmbeddingPort,
        *,
        mode: HybridRetrievalMode,
        profile_id: str = SEMANTIC_PROFILE_ID,
    ) -> None:
        if mode not in ("semantic", "hybrid"):
            raise ValueError("mode must be semantic or hybrid")
        if profile_id != SEMANTIC_PROFILE_ID:
            raise ValueError("profile_id must be the exact semantic profile")
        self._session_factory = session_factory
        self._active_source_ids = self._validate_sources(active_source_ids)
        self._embedder = embedder
        self._mode = mode
        self._profile_id = profile_id

    @classmethod
    async def coverage_complete_for(
        cls,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
        *,
        profile_id: str = SEMANTIC_PROFILE_ID,
    ) -> bool:
        """Return whether every latest strict-trust chunk has the exact semantic row."""

        if profile_id != SEMANTIC_PROFILE_ID:
            return False
        sources = cls._validate_sources(active_source_ids)
        latest = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        strict_provenance = cls._strict_provenance_exists()
        # An exact-row predicate deliberately does not trust a local-hash row as ready.
        exact = exists(
            select(ChunkEmbedding.id).where(
                ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                ChunkEmbedding.embedding_model_id == profile_id,
                ChunkEmbedding.dimension == SEMANTIC_DIMENSION,
                ChunkEmbedding.embedding_kind == "semantic",
            )
        )
        statement = (
            select(func.count(DocumentChunk.id))
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .where(
                LegalDocument.source_id.in_(sources),
                DocumentVersion.version_number == latest,
                strict_provenance,
                ~exact,
            )
        )
        async with session_factory() as session:
            missing_count = await session.scalar(statement)
        return int(missing_count or 0) == 0

    async def coverage_complete(self) -> bool:
        """Expose exact-profile readiness without embedding or opening a write transaction."""

        return await self.coverage_complete_for(
            self._session_factory, self._active_source_ids, profile_id=self._profile_id
        )

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        """Embed before database work, then write one exact evidence run."""

        vector = await self._query_vector_or_none(request)
        ready = vector is not None and await self.coverage_complete()
        fallback = not ready
        if fallback and self._mode == "semantic":
            return await self.persist_zero_evidence_run(
                request, RetrievalDecision.NO_RESULTS, RetrievalReason.SEMANTIC_UNAVAILABLE
            )
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                    if fallback:
                        raw = await self._select_lexical(session, request)
                        candidates = self._rank_hybrid(raw, (), request.top_k)
                        return await self._persist(
                            session,
                            request,
                            candidates,
                            strategy="postgresql_hybrid",
                            strategy_version="v4_hybrid_semantic_fallback",
                            reason=(
                                RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE
                                if candidates
                                else RetrievalReason.SEMANTIC_UNAVAILABLE
                            ),
                        )
                    assert vector is not None
                    await session.execute(text("SET LOCAL enable_indexscan = off"))
                    await session.execute(text("SET LOCAL enable_bitmapscan = off"))
                    semantic = await self._select_semantic(session, vector, request.top_k)
                    await session.execute(text("SET LOCAL enable_indexscan = on"))
                    await session.execute(text("SET LOCAL enable_bitmapscan = on"))
                    if self._mode == "semantic":
                        return await self._persist(
                            session,
                            request,
                            semantic[: request.top_k],
                            strategy="postgresql_semantic",
                            strategy_version="v4_semantic_exact",
                            reason=(
                                RetrievalReason.SEMANTIC_EVIDENCE_AVAILABLE
                                if semantic
                                else RetrievalReason.NO_SEMANTIC_MATCH
                            ),
                        )
                    raw = await self._select_lexical(session, request)
                    ranked = self._rank_hybrid(raw, semantic, request.top_k)
                    return await self._persist(
                        session,
                        request,
                        ranked,
                        strategy="postgresql_hybrid",
                        strategy_version="v4_hybrid_exact",
                        reason=(
                            RetrievalReason.HYBRID_EVIDENCE_AVAILABLE
                            if ranked
                            else RetrievalReason.NO_HYBRID_MATCH
                        ),
                    )
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE) from None

    async def persist_zero_evidence_run(
        self,
        request: RetrievalRequest,
        decision: RetrievalDecision,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        """Persist a safe zero-evidence outcome without calling the embedder."""

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    return await self._persist(
                        session,
                        request,
                        (),
                        strategy="postgresql_semantic"
                        if self._mode == "semantic"
                        else "postgresql_hybrid",
                        strategy_version="v4_semantic_exact"
                        if self._mode == "semantic"
                        else "v4_hybrid_exact",
                        decision=decision,
                        reason=reason,
                    )
        except Exception:
            raise RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE) from None

    async def _query_vector_or_none(self, request: RetrievalRequest) -> tuple[float, ...] | None:
        try:
            batch = await self._embedder.embed_query(request.query)
            return self._validated_query_vector(batch)
        except SemanticError:
            return None
        except Exception:
            return None

    def _validated_query_vector(self, batch: object) -> tuple[float, ...] | None:
        if (
            not isinstance(batch, SemanticEmbeddingBatch)
            or batch.profile.profile_id != self._profile_id
        ):
            return None
        if len(batch.vectors) != 1:
            return None
        vector = batch.vectors[0]
        if len(vector) != SEMANTIC_DIMENSION or not all(isfinite(item) for item in vector):
            return None
        return vector

    @staticmethod
    def _strict_provenance_exists():
        return (
            select(SourceProvenanceRecord.id)
            .where(
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
            .correlate(DocumentVersion)
            .exists()
        )

    @staticmethod
    def _selected_provenance_id():
        return (
            select(SourceProvenanceRecord.id)
            .where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                SourceProvenanceRecord.provenance_type.in_(("source_fetch", "manual_snapshot")),
            )
            .order_by(SourceProvenanceRecord.retrieved_at.asc(), SourceProvenanceRecord.id.asc())
            .limit(1)
            .correlate(DocumentVersion)
            .scalar_subquery()
        )

    async def _select_semantic(
        self, session: AsyncSession, vector: tuple[float, ...], top_k: int
    ) -> tuple[_Candidate, ...]:
        latest = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        provenance_id = self._selected_provenance_id()
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                SourceProvenanceRecord.id,
                SourceProvenanceRecord.document_version_id,
                (1 - distance).label("semantic_score"),
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == self._profile_id,
                    ChunkEmbedding.embedding_kind == "semantic",
                    ChunkEmbedding.dimension == SEMANTIC_DIMENSION,
                ),
            )
            .outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == latest,
                self._strict_provenance_exists(),
                provenance_id.is_not(None),
            )
            .order_by(distance.asc(), DocumentChunk.id.asc())
            .limit(min(top_k + 2, 8))
        )
        rows = (await session.execute(statement)).all()
        return tuple(
            _Candidate(row[0], row[1], row[2], row[3], semantic_score=float(row[4]))
            for row in rows
        )

    async def _select_lexical(
        self, session: AsyncSession, request: RetrievalRequest
    ) -> tuple[_Candidate, ...]:
        latest = (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )
        provenance_id = self._selected_provenance_id()
        parsed = select(
            func.websearch_to_tsquery(text("'pg_catalog.simple'::regconfig"), bindparam("query"))
            .label("parsed_query")
        ).cte("parsed_query")
        score = func.ts_rank_cd(DocumentChunk.search_vector, parsed.c.parsed_query)
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                SourceProvenanceRecord.id,
                SourceProvenanceRecord.document_version_id,
                score,
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .join(parsed, true())
            .where(
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == latest,
                self._strict_provenance_exists(),
                provenance_id.is_not(None),
                func.numnode(parsed.c.parsed_query) > 0,
                DocumentChunk.search_vector.op("@@")(parsed.c.parsed_query),
            )
            .order_by(score.desc(), DocumentChunk.id.asc())
            .limit(min(request.top_k + 2, 8))
        )
        rows = (await session.execute(statement, {"query": request.query})).all()
        return tuple(
            _Candidate(row[0], row[1], row[2], row[3], lexical_score=float(row[4]))
            for row in rows
        )

    @staticmethod
    def _rank_hybrid(
        raw: tuple[_Candidate, ...], semantic: tuple[_Candidate, ...], top_k: int
    ) -> tuple[_Candidate, ...]:
        scores: dict[UUID, float] = {}
        rows: dict[UUID, _Candidate] = {}
        raw_ids = {row.chunk_id for row in raw}
        for candidates in (raw, semantic):
            for rank, candidate in enumerate(candidates, start=1):
                scores[candidate.chunk_id] = scores.get(candidate.chunk_id, 0) + 1 / (_RRF_K + rank)
                previous = rows.get(candidate.chunk_id)
                rows[candidate.chunk_id] = (
                    candidate
                    if previous is None
                    else replace(
                        previous,
                        lexical_score=(
                            previous.lexical_score
                            if previous.lexical_score is not None
                            else candidate.lexical_score
                        ),
                        semantic_score=(
                            previous.semantic_score
                            if previous.semantic_score is not None
                            else candidate.semantic_score
                        ),
                    )
                )
        selected = sorted(
            scores, key=lambda item: (-scores[item], -(item in raw_ids), item)
        )[:top_k]
        if raw and raw[0].chunk_id not in selected:
            selected[-1] = raw[0].chunk_id
            selected.sort(key=lambda item: (-scores[item], -(item in raw_ids), item))
        return tuple(rows[item] for item in selected)

    async def _persist(
        self,
        session: AsyncSession,
        request: RetrievalRequest,
        candidates: tuple[_Candidate, ...],
        *,
        strategy: str,
        strategy_version: str,
        decision: RetrievalDecision | None = None,
        reason: RetrievalReason | None = None,
    ) -> RetrievalResult:
        if any(
            row.provenance_id is None or row.provenance_version_id != row.version_id
            for row in candidates
        ):
            decision = RetrievalDecision.INVALID_EVIDENCE_CHAIN
            reason = RetrievalReason.INVALID_EVIDENCE_CHAIN
            candidates = ()
        if decision is None:
            decision = (
                RetrievalDecision.EVIDENCE_AVAILABLE
                if candidates
                else RetrievalDecision.NO_RESULTS
            )
        if reason is None:
            reason = (
                RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE
                if candidates
                else RetrievalReason.NO_LEXICAL_MATCH
            )
        run = RetrievalRun(
            id=uuid4(),
            strategy=strategy,
            strategy_version=strategy_version,
            scope=RetrievalScope.LATEST_INGESTED.value,
            trust_scope=request.trust_scope.value,
            query_max_chars=QUERY_MAX_CHARS,
            top_k=request.top_k,
            candidate_count=len(candidates),
            citation_count=len(candidates),
            evidence_decision=decision.value,
            evidence_reason=reason.value,
        )
        session.add(run)
        await session.flush()
        output: list[RetrievalCandidate] = []
        for rank, candidate in enumerate(candidates, start=1):
            assert candidate.provenance_id is not None
            citation_id = uuid4()
            session.add(
                CitationRecord(
                    id=citation_id,
                    retrieval_run_id=run.id,
                    document_chunk_id=candidate.chunk_id,
                    source_provenance_record_id=candidate.provenance_id,
                    rank=rank,
                    lexical_score=candidate.lexical_score,
                    semantic_score=candidate.semantic_score,
                    reranker_score=candidate.reranker_score,
                )
            )
            output.append(
                RetrievalCandidate(
                    citation_id=citation_id,
                    document_chunk_id=candidate.chunk_id,
                    rank=rank,
                    lexical_score=candidate.lexical_score,
                    semantic_score=candidate.semantic_score,
                    reranker_score=candidate.reranker_score,
                )
            )
        return RetrievalResult(
            retrieval_run_id=run.id,
            candidates=tuple(output),
            candidate_count=len(output),
            citation_count=len(output),
            decision=decision,
            reason=reason,
        )

    @staticmethod
    def _validate_sources(active_source_ids: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not isinstance(active_source_ids, tuple)
            or not 1 <= len(active_source_ids) <= _MAX_SOURCES
            or len(active_source_ids) != len(set(active_source_ids))
            or any(
                not isinstance(item, str) or not item or len(item) > 32
                for item in active_source_ids
            )
        ):
            raise ValueError("active_source_ids must be a unique bounded tuple")
        return active_source_ids
