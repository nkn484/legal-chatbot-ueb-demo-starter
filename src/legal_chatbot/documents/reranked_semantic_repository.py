"""Bounded exact-semantic retrieval with optional offline cross-encoder reranking."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from math import isfinite
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.hybrid_retrieval_repository import PostgresHybridRetrievalRepository
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.reranking.models import RerankCandidate, RerankRequest, RerankResult
from legal_chatbot.reranking.port import RerankerPort
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
from legal_chatbot.semantic.models import SemanticEmbeddingBatch
from legal_chatbot.semantic.ports import SemanticEmbeddingPort

_WINDOW = 8
_CONTEXT = 400
_HYDRATED_MAX = 2_000


@dataclass(frozen=True)
class _SemanticChild:
    chunk_id: UUID
    version_id: UUID
    provenance_id: UUID
    ordinal: int
    semantic_score: float
    text: str = ""
    reranker_score: float | None = None


@dataclass(frozen=True)
class RerankedRetrievalDiagnostics:
    """Content-free server-owned counts for one completed reranked retrieval."""

    strategy_version: str
    pre_rerank_chunk_candidate_count: int
    pre_rerank_document_version_count: int
    post_collapse_document_version_count: int
    final_citation_document_version_count: int
    reranker_fallback: bool


RerankedRetrievalObserver = Callable[[RerankedRetrievalDiagnostics], None]


class PostgresRerankedSemanticRepository:
    """Use exact semantic candidates only; reranking is outside both DB transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
        embedder: SemanticEmbeddingPort,
        reranker: RerankerPort,
        *,
        timeout_seconds: float = 5.0,
        observer: RerankedRetrievalObserver | None = None,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 30.0:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        self._session_factory = session_factory
        self._active_source_ids = PostgresHybridRetrievalRepository._validate_sources(
            active_source_ids
        )
        self._embedder = embedder
        self._reranker = reranker
        self._timeout_seconds = timeout_seconds
        self._observer = observer

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        vector = await self._embed_query(request)
        if vector is None or not await self._coverage_complete():
            return await self.persist_zero_evidence_run(
                request, RetrievalDecision.NO_RESULTS, RetrievalReason.SEMANTIC_UNAVAILABLE
            )
        read_result = await self._read_candidates(vector)
        children, pre_chunk_count, pre_version_count, post_collapse_count = read_result
        if not children:
            result = await self.persist_zero_evidence_run(
                request,
                RetrievalDecision.NO_RESULTS,
                RetrievalReason.NO_SEMANTIC_MATCH,
                _emit_diagnostics=False,
            )
            self._emit(
                "v5_semantic_exact_reranked", pre_chunk_count, pre_version_count, 0, 0, False
            )
            return result
        ranked, fallback = await self._rerank(request, children)
        return await self._write_candidates(
            request, ranked, fallback, pre_chunk_count, pre_version_count, post_collapse_count
        )

    async def persist_zero_evidence_run(
        self,
        request: RetrievalRequest,
        decision: RetrievalDecision,
        reason: RetrievalReason,
        *,
        _emit_diagnostics: bool = True,
    ) -> RetrievalResult:
        async with self._session_factory() as session:
            async with session.begin():
                result = await self._persist(
                    session, request, (), "v5_semantic_exact_reranked", decision, reason
                )
        if _emit_diagnostics:
            self._emit("v5_semantic_exact_reranked", 0, 0, 0, 0, False)
        return result

    def _emit(
        self,
        strategy_version: str,
        pre_chunk_count: int,
        pre_version_count: int,
        post_collapse_count: int,
        final_version_count: int,
        fallback: bool,
    ) -> None:
        if self._observer is not None:
            self._observer(
                RerankedRetrievalDiagnostics(
                    strategy_version=strategy_version,
                    pre_rerank_chunk_candidate_count=pre_chunk_count,
                    pre_rerank_document_version_count=pre_version_count,
                    post_collapse_document_version_count=post_collapse_count,
                    final_citation_document_version_count=final_version_count,
                    reranker_fallback=fallback,
                )
            )

    async def _embed_query(self, request: RetrievalRequest) -> tuple[float, ...] | None:
        try:
            batch = await self._embedder.embed_query(request.query)
            if not isinstance(batch, SemanticEmbeddingBatch) or len(batch.vectors) != 1:
                return None
            vector = batch.vectors[0]
            if len(vector) != SEMANTIC_DIMENSION or not all(isfinite(value) for value in vector):
                return None
            return vector
        except Exception:
            return None

    async def _coverage_complete(self) -> bool:
        return await PostgresHybridRetrievalRepository.coverage_complete_for(
            self._session_factory, self._active_source_ids
        )

    @staticmethod
    def _latest_version():
        return (
            select(func.max(DocumentVersion.version_number))
            .where(DocumentVersion.document_id == LegalDocument.id)
            .correlate(LegalDocument)
            .scalar_subquery()
        )

    @staticmethod
    def _strict_provenance():
        return (
            select(SourceProvenanceRecord.id)
            .where(
                SourceProvenanceRecord.document_version_id == DocumentVersion.id,
                SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                SourceProvenanceRecord.provenance_type.in_(("source_fetch", "manual_snapshot")),
            )
            .correlate(DocumentVersion)
            .exists()
        )

    @staticmethod
    def _provenance_id():
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

    async def _read_candidates(
        self, vector: tuple[float, ...]
    ) -> tuple[tuple[_SemanticChild, ...], int, int, int]:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                await session.execute(text("SET LOCAL enable_indexscan = off"))
                await session.execute(text("SET LOCAL enable_bitmapscan = off"))
                candidates = await self._select_exact(session, vector)
                collapsed = self._collapse_versions(candidates)
                hydrated = await self._hydrate(session, collapsed)
                return (
                    hydrated,
                    len(candidates),
                    len({item.version_id for item in candidates}),
                    len(collapsed),
                )

    async def _select_exact(
        self, session: AsyncSession, vector: tuple[float, ...]
    ) -> tuple[_SemanticChild, ...]:
        provenance_id = self._provenance_id()
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        statement = (
            select(
                DocumentChunk.id,
                DocumentChunk.document_version_id,
                SourceProvenanceRecord.id,
                DocumentChunk.ordinal,
                (1 - distance).label("semantic_score"),
            )
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
                    ChunkEmbedding.embedding_kind == "semantic",
                    ChunkEmbedding.dimension == SEMANTIC_DIMENSION,
                ),
            )
            .outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == self._latest_version(),
                self._strict_provenance(),
                provenance_id.is_not(None),
            )
            .order_by(distance.asc(), DocumentChunk.ordinal.asc(), DocumentChunk.id.asc())
            .limit(_WINDOW)
        )
        rows = (await session.execute(statement)).all()
        return tuple(_SemanticChild(row[0], row[1], row[2], row[3], float(row[4])) for row in rows)

    @staticmethod
    def _collapse_versions(children: tuple[_SemanticChild, ...]) -> tuple[_SemanticChild, ...]:
        selected: dict[UUID, _SemanticChild] = {}
        for child in children:
            previous = selected.get(child.version_id)
            if previous is None or (-child.semantic_score, child.ordinal, child.chunk_id) < (
                -previous.semantic_score,
                previous.ordinal,
                previous.chunk_id,
            ):
                selected[child.version_id] = child
        return tuple(
            sorted(
                selected.values(),
                key=lambda item: (-item.semantic_score, item.ordinal, item.chunk_id),
            )
        )

    async def _hydrate(
        self, session: AsyncSession, children: tuple[_SemanticChild, ...]
    ) -> tuple[_SemanticChild, ...]:
        needed_ordinals: dict[UUID, set[int]] = {}
        for child in children:
            needed_ordinals.setdefault(child.version_id, set()).update(
                (max(0, child.ordinal - 1), child.ordinal, child.ordinal + 1)
            )
        predicates = [
            and_(
                DocumentChunk.document_version_id == version_id,
                DocumentChunk.ordinal.in_(ordinals),
            )
            for version_id, ordinals in needed_ordinals.items()
        ]
        rows = (
            await session.execute(
                select(
                    DocumentChunk.document_version_id,
                    DocumentChunk.ordinal,
                    DocumentChunk.content_text,
                    DocumentChunk.locator,
                ).where(or_(*predicates))
            )
        ).all()
        chunks = {(row[0], row[1]): (row[2], row[3]) for row in rows}
        hydrated: list[_SemanticChild] = []
        for child in children:
            current = chunks.get((child.version_id, child.ordinal))
            if current is None:
                continue
            predecessor_row = chunks.get((child.version_id, child.ordinal - 1), ("", None))
            predecessor = predecessor_row[0][-_CONTEXT:]
            successor = chunks.get((child.version_id, child.ordinal + 1), ("", None))[0][:_CONTEXT]
            locator = current[1]
            label = ""
            if isinstance(locator, dict):
                label = str(locator.get("label", "")).strip()
            parts = tuple(part for part in (label, predecessor, current[0], successor) if part)
            hydrated.append(replace(child, text="\n".join(parts)[:_HYDRATED_MAX]))
        return tuple(hydrated)

    async def _rerank(
        self, request: RetrievalRequest, children: tuple[_SemanticChild, ...]
    ) -> tuple[tuple[_SemanticChild, ...], bool]:
        rerank_request = RerankRequest(
            query=request.query,
            candidates=tuple(
                RerankCandidate(chunk_id=str(item.chunk_id), text=item.text) for item in children
            ),
        )
        try:
            result = await asyncio.wait_for(
                self._reranker.rerank(rerank_request), timeout=self._timeout_seconds
            )
            return self._apply_rerank(children, result), False
        except (TimeoutError, asyncio.CancelledError, Exception):
            return children, True

    @staticmethod
    def _apply_rerank(
        children: tuple[_SemanticChild, ...], result: RerankResult
    ) -> tuple[_SemanticChild, ...]:
        expected = tuple(str(item.chunk_id) for item in children)
        if result.candidate_ids != expected or len(result.scores) != len(children):
            raise ValueError("reranker result alignment invalid")
        scored = tuple(
            replace(child, reranker_score=score)
            for child, score in zip(children, result.scores, strict=True)
        )
        return tuple(
            sorted(
                scored,
                key=lambda item: (-(item.reranker_score or 0.0), item.ordinal, item.chunk_id),
            )
        )

    async def _write_candidates(
        self,
        request: RetrievalRequest,
        children: tuple[_SemanticChild, ...],
        fallback: bool,
        pre_chunk_count: int,
        pre_version_count: int,
        post_collapse_count: int,
    ) -> RetrievalResult:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                valid = await self._revalidate(session, children)
                selected = valid[: request.top_k]
                strategy_version = (
                    "v5_semantic_exact_reranker_fallback"
                    if fallback
                    else "v5_semantic_exact_reranked"
                )
                result = await self._persist(
                    session,
                    request,
                    selected,
                    strategy_version,
                    RetrievalDecision.EVIDENCE_AVAILABLE if valid else RetrievalDecision.NO_RESULTS,
                    (
                        RetrievalReason.SEMANTIC_EVIDENCE_AVAILABLE
                        if valid
                        else RetrievalReason.NO_SEMANTIC_MATCH
                    ),
                )
        self._emit(
            strategy_version,
            pre_chunk_count,
            pre_version_count,
            post_collapse_count,
            len({item.version_id for item in selected}),
            fallback,
        )
        return result

    async def _revalidate(
        self, session: AsyncSession, children: tuple[_SemanticChild, ...]
    ) -> tuple[_SemanticChild, ...]:
        if not children:
            return ()
        ids = tuple(item.chunk_id for item in children)
        provenance_id = self._provenance_id()
        statement = (
            select(DocumentChunk.id, DocumentChunk.document_version_id, SourceProvenanceRecord.id)
            .select_from(DocumentChunk)
            .join(DocumentVersion, DocumentChunk.document_version_id == DocumentVersion.id)
            .join(LegalDocument, DocumentVersion.document_id == LegalDocument.id)
            .join(
                ChunkEmbedding,
                and_(
                    ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                    ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
                    ChunkEmbedding.embedding_kind == "semantic",
                    ChunkEmbedding.dimension == SEMANTIC_DIMENSION,
                ),
            )
            .outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance_id)
            .where(
                DocumentChunk.id.in_(ids),
                LegalDocument.source_id.in_(self._active_source_ids),
                DocumentVersion.version_number == self._latest_version(),
                self._strict_provenance(),
                provenance_id.is_not(None),
            )
        )
        valid = {(row[0], row[1], row[2]) for row in (await session.execute(statement)).all()}
        return tuple(
            item
            for item in children
            if (item.chunk_id, item.version_id, item.provenance_id) in valid
        )

    async def _persist(
        self,
        session: AsyncSession,
        request: RetrievalRequest,
        children: tuple[_SemanticChild, ...],
        version: str,
        decision: RetrievalDecision,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        run = RetrievalRun(
            id=uuid4(), strategy="postgresql_semantic", strategy_version=version,
            scope=RetrievalScope.LATEST_INGESTED.value,
            trust_scope=request.trust_scope.value,
            query_max_chars=QUERY_MAX_CHARS,
            top_k=request.top_k,
            candidate_count=len(children),
            citation_count=len(children),
            evidence_decision=decision.value,
            evidence_reason=reason.value,
        )
        session.add(run)
        await session.flush()
        candidates: list[RetrievalCandidate] = []
        for rank, child in enumerate(children, start=1):
            citation_id = uuid4()
            session.add(CitationRecord(
                id=citation_id, retrieval_run_id=run.id, document_chunk_id=child.chunk_id,
                source_provenance_record_id=child.provenance_id, rank=rank, lexical_score=None,
                semantic_score=child.semantic_score, reranker_score=child.reranker_score,
            ))
            candidates.append(RetrievalCandidate(
                citation_id=citation_id, document_chunk_id=child.chunk_id, rank=rank,
                lexical_score=None, semantic_score=child.semantic_score,
                reranker_score=child.reranker_score,
            ))
        return RetrievalResult(
            retrieval_run_id=run.id, candidates=tuple(candidates), candidate_count=len(candidates),
            citation_count=len(candidates), decision=decision, reason=reason,
        )
