"""Bounded exact-semantic retrieval with conservative metadata repair discovery."""
# ruff: noqa: E501

from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from itertools import combinations
from math import isfinite
from uuid import UUID, uuid4

from sqlalchemy import and_, bindparam, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.hybrid_retrieval_repository import PostgresHybridRetrievalRepository
from legal_chatbot.documents.metadata_normalization import normalize_document_number
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.reranking.constants import RERANKER_CANDIDATE_MAX
from legal_chatbot.reranking.models import RerankCandidate, RerankRequest
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

_SEMANTIC_LIMIT = 20
_VERSION_LIMIT = 16
_RERANK_LIMIT = RERANKER_CANDIDATE_MAX
_TITLE_LIMIT = 8
_NUMBER_LIMIT = 2
_RRF_K = 60
_CONTEXT = 400
_HYDRATED_MAX = 2_000
_NUMBER = re.compile(
    r"(?<![\w/])\d{1,6}(?:\s*/\s*(?:[\wÀ-ỹĐđ.]*-[\wÀ-ỹĐđ.-]*\s+"
    r"[\wÀ-ỹĐđ.-]{1,32}|[\wÀ-ỹĐđ.-]{1,32})){1,3}(?![\w/])",
    re.UNICODE,
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset({
    "các", "của", "cho", "được", "là", "luật", "nghị", "định", "quy", "quyết",
    "theo", "và", "về", "văn", "bản", "xin", "hỏi", "tôi", "có", "không",
})


@dataclass(frozen=True)
class MetadataRepairDiagnostics:
    strategy_version: str
    semantic_candidate_count: int
    exact_identity_candidate_count: int
    title_candidate_count: int
    ambiguous_identity_count: int
    metadata_no_support_count: int
    pre_dedup_count: int
    post_document_collapse_count: int
    reranker_input_count: int
    final_count: int
    reranker_fallback: bool
    arm_contribution_counts: dict[str, int]
    rejection_reason_counts: dict[str, int]


@dataclass(frozen=True)
class _Candidate:
    chunk_id: UUID
    version_id: UUID
    provenance_id: UUID
    ordinal: int
    semantic_score: float
    arms: tuple[str, ...]
    text: str = ""
    reranker_score: float | None = None


MetadataObserver = Callable[[MetadataRepairDiagnostics], None]


def extract_document_numbers(question: str) -> tuple[str, ...]:
    """Return at most two normalized user-supplied exact-number keys."""

    values: list[str] = []
    normalized_question = unicodedata.normalize("NFC", question).translate(
        str.maketrans({character: "-" for character in "‐‑‒–—"})
    )
    for match in _NUMBER.finditer(normalized_question):
        normalized = normalize_document_number(match.group(0))
        if normalized is not None and normalized not in values:
            values.append(normalized)
        if len(values) == _NUMBER_LIMIT:
            break
    return tuple(values)


def compile_title_tokens(question: str) -> tuple[str, ...]:
    """Derive at most four meaningful title terms; reject singleton broad searches."""

    tokens = []
    for token in _TOKEN.findall(unicodedata.normalize("NFC", question).casefold()):
        if token not in _STOPWORDS and len(token) > 1 and token not in tokens:
            tokens.append(token)
        if len(tokens) == 4:
            break
    return tuple(tokens) if len(tokens) >= 2 else ()


def compile_title_tsquery(question: str) -> str:
    """Compile a safe bounded title query requiring at least two terms."""

    tokens = compile_title_tokens(question)
    if not tokens or any(_TOKEN.fullmatch(token) is None for token in tokens):
        return ""
    return " | ".join(f"({left} & {right})" for left, right in combinations(tokens, 2))


class PostgresMetadataRepairRetrievalRepository:
    """Exact E5 evidence plus conservative number/title discovery with semantic support."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        active_source_ids: tuple[str, ...],
        embedder: SemanticEmbeddingPort,
        reranker: RerankerPort,
        *,
        timeout_seconds: float = 5.0,
        observer: MetadataObserver | None = None,
    ) -> None:
        if not 0.1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0.1 and 30")
        self._session_factory = session_factory
        self._active_source_ids = PostgresHybridRetrievalRepository._validate_sources(active_source_ids)
        self._embedder = embedder
        self._reranker = reranker
        self._timeout_seconds = timeout_seconds
        self._observer = observer

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        vector = await self._embed_query(request)
        if vector is None or not await self._coverage_complete():
            return await self._zero(request, RetrievalReason.SEMANTIC_UNAVAILABLE, "v6_semantic_exact_metadata_unavailable")
        candidates, diagnostics = await self._read(request, vector)
        if not candidates:
            return await self._zero(
                request, RetrievalReason.NO_SEMANTIC_MATCH, "v6_semantic_exact_metadata_reranked", diagnostics
            )
        reranked, fallback = await self._rerank(request, candidates)
        if not fallback:
            rejections = dict(diagnostics.rejection_reason_counts)
            rejections["RERANK_DEMOTION"] = self._rerank_demotion(
                candidates, reranked, request.top_k
            )
            diagnostics = replace(diagnostics, rejection_reason_counts=rejections)
        return await self._write(request, reranked, fallback, diagnostics)

    async def persist_zero_evidence_run(
        self, request: RetrievalRequest, decision: RetrievalDecision, reason: RetrievalReason
    ) -> RetrievalResult:
        return await self._zero(request, reason, "v6_semantic_exact_metadata_reranked", decision=decision)

    async def _zero(
        self,
        request: RetrievalRequest,
        reason: RetrievalReason,
        version: str,
        diagnostics: MetadataRepairDiagnostics | None = None,
        *,
        decision: RetrievalDecision = RetrievalDecision.NO_RESULTS,
    ) -> RetrievalResult:
        async with self._session_factory() as session:
            async with session.begin():
                result = await self._persist(session, request, (), version, decision, reason)
        self._emit(diagnostics or self._diagnostics(version), final_count=0, fallback=False)
        return result

    async def _embed_query(self, request: RetrievalRequest) -> tuple[float, ...] | None:
        try:
            batch = await self._embedder.embed_query(request.query)
            if not isinstance(batch, SemanticEmbeddingBatch) or len(batch.vectors) != 1:
                return None
            vector = batch.vectors[0]
            return vector if len(vector) == SEMANTIC_DIMENSION and all(isfinite(x) for x in vector) else None
        except Exception:
            return None

    async def _coverage_complete(self) -> bool:
        return await PostgresHybridRetrievalRepository.coverage_complete_for(
            self._session_factory, self._active_source_ids
        )

    @staticmethod
    def _latest():
        return select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == LegalDocument.id
        ).correlate(LegalDocument).scalar_subquery()

    @staticmethod
    def _strict_exists():
        return select(SourceProvenanceRecord.id).where(
            SourceProvenanceRecord.document_version_id == DocumentVersion.id,
            SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
            SourceProvenanceRecord.provenance_type.in_(("source_fetch", "manual_snapshot")),
        ).correlate(DocumentVersion).exists()

    @staticmethod
    def _provenance_id():
        return select(SourceProvenanceRecord.id).where(
            SourceProvenanceRecord.document_version_id == DocumentVersion.id,
            SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
            SourceProvenanceRecord.provenance_type.in_(("source_fetch", "manual_snapshot")),
        ).order_by(SourceProvenanceRecord.retrieved_at.asc(), SourceProvenanceRecord.id.asc()).limit(1).correlate(DocumentVersion).scalar_subquery()

    def _eligible(self):
        return (
            LegalDocument.source_id.in_(self._active_source_ids),
            DocumentVersion.version_number == self._latest(),
            self._strict_exists(),
        )

    async def _read(
        self, request: RetrievalRequest, vector: tuple[float, ...]
    ) -> tuple[tuple[_Candidate, ...], MetadataRepairDiagnostics]:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                await session.execute(text("SET LOCAL enable_indexscan = off"))
                await session.execute(text("SET LOCAL enable_bitmapscan = off"))
                semantic = await self._semantic(session, vector, _SEMANTIC_LIMIT)
                await session.execute(text("SET LOCAL enable_indexscan = on"))
                await session.execute(text("SET LOCAL enable_bitmapscan = on"))
                semantic_collapsed = self._collapse(semantic)
                semantic_versions = semantic_collapsed[:_VERSION_LIMIT]
                numbers, ambiguous = await self._identity_versions(session, request.query)
                titles = await self._title_versions(session, request.query)
                metadata_versions = tuple(dict.fromkeys((*numbers, *titles)))
                await session.execute(text("SET LOCAL enable_indexscan = off"))
                await session.execute(text("SET LOCAL enable_bitmapscan = off"))
                supported, unsupported = await self._supporting_children(session, vector, metadata_versions)
                await session.execute(text("SET LOCAL enable_indexscan = on"))
                await session.execute(text("SET LOCAL enable_bitmapscan = on"))
                merged = self._rrf(semantic_versions, supported, numbers, titles)
                hydrated = await self._hydrate(session, merged[:_RERANK_LIMIT])
        raw = (*semantic, *supported)
        rejections = self._rejection_counts(
            document_collapse=len(raw) - len({item.version_id for item in raw}),
            semantic_rank_cutoff=max(0, len(semantic_collapsed) - len(semantic_versions)),
            duplicate_chunk=len(raw) - len({item.chunk_id for item in raw}),
            ambiguous=ambiguous,
            unsupported=unsupported,
        )
        diagnostics = self._diagnostics(
            "v6_semantic_exact_metadata_reranked",
            semantic=len(semantic),
            identity=len(numbers),
            title=len(titles),
            ambiguous=ambiguous,
            unsupported=unsupported,
            pre=len(raw),
            post=len(merged),
            reranker=len(hydrated),
        )
        diagnostics = replace(
            diagnostics,
            arm_contribution_counts=dict(Counter(arm for item in hydrated for arm in item.arms)),
            rejection_reason_counts=rejections,
        )
        return hydrated, diagnostics

    async def _semantic(self, session: AsyncSession, vector: tuple[float, ...], limit: int) -> tuple[_Candidate, ...]:
        provenance = self._provenance_id()
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        statement = select(
            DocumentChunk.id, DocumentChunk.document_version_id, SourceProvenanceRecord.id,
            DocumentChunk.ordinal, (1 - distance).label("semantic_score"),
        ).select_from(DocumentChunk).join(DocumentVersion).join(LegalDocument).join(
            ChunkEmbedding,
            and_(ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                 ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
                 ChunkEmbedding.embedding_kind == "semantic", ChunkEmbedding.dimension == SEMANTIC_DIMENSION),
        ).outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance).where(
            *self._eligible(), provenance.is_not(None)
        ).order_by(distance.asc(), DocumentChunk.ordinal.asc(), DocumentChunk.id.asc()).limit(limit)
        rows = (await session.execute(statement)).all()
        return tuple(_Candidate(row[0], row[1], row[2], row[3], float(row[4]), ("semantic",)) for row in rows)

    @staticmethod
    def _collapse(candidates: tuple[_Candidate, ...]) -> tuple[_Candidate, ...]:
        chosen: dict[UUID, _Candidate] = {}
        for candidate in candidates:
            old = chosen.get(candidate.version_id)
            if old is None or (-candidate.semantic_score, candidate.ordinal, candidate.chunk_id) < (
                -old.semantic_score, old.ordinal, old.chunk_id
            ):
                chosen[candidate.version_id] = candidate
        return tuple(sorted(chosen.values(), key=lambda x: (-x.semantic_score, x.ordinal, x.chunk_id)))

    async def _identity_versions(self, session: AsyncSession, question: str) -> tuple[tuple[UUID, ...], int]:
        selected: list[UUID] = []
        ambiguous = 0
        for number in extract_document_numbers(question):
            rows = (await session.execute(select(
                LegalDocument.id, DocumentVersion.id
            ).select_from(DocumentVersion).join(LegalDocument).where(
                *self._eligible(), DocumentVersion.document_number_normalized == number
            ).distinct().order_by(LegalDocument.id.asc(), DocumentVersion.id.asc()))).all()
            identities = {row[0]: row[1] for row in rows}
            if len(identities) == 1:
                selected.append(next(iter(identities.values())))
            elif len(identities) > 1:
                ambiguous += 1
        return tuple(selected), ambiguous

    async def _title_versions(self, session: AsyncSession, question: str) -> tuple[UUID, ...]:
        query = compile_title_tsquery(question)
        if not query:
            return ()
        parsed = func.to_tsquery(text("'pg_catalog.simple'::regconfig"), bindparam("title_query"))
        score = func.ts_rank_cd(DocumentVersion.title_search_vector, parsed)
        rows = (await session.execute(select(DocumentVersion.id).join(LegalDocument).where(
            *self._eligible(), DocumentVersion.title_search_vector.op("@@")(parsed)
        ).order_by(score.desc(), DocumentVersion.id.asc()).limit(_TITLE_LIMIT), {"title_query": query})).all()
        return tuple(row[0] for row in rows)

    async def _supporting_children(
        self, session: AsyncSession, vector: tuple[float, ...], versions: tuple[UUID, ...]
    ) -> tuple[tuple[_Candidate, ...], int]:
        supported: list[_Candidate] = []
        missing = 0
        for version_id in versions:
            candidates = await self._semantic_for_versions(session, vector, (version_id,))
            if candidates:
                supported.append(candidates[0])
            else:
                missing += 1
        return tuple(supported), missing

    async def _semantic_for_versions(self, session: AsyncSession, vector: tuple[float, ...], versions: tuple[UUID, ...]) -> tuple[_Candidate, ...]:
        if not versions:
            return ()
        provenance = self._provenance_id()
        distance = ChunkEmbedding.embedding.cosine_distance(list(vector))
        rows = (await session.execute(select(
            DocumentChunk.id, DocumentChunk.document_version_id, SourceProvenanceRecord.id,
            DocumentChunk.ordinal, (1 - distance).label("semantic_score"),
        ).select_from(DocumentChunk).join(DocumentVersion).join(LegalDocument).join(
            ChunkEmbedding,
            and_(ChunkEmbedding.document_chunk_id == DocumentChunk.id,
                 ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID,
                 ChunkEmbedding.embedding_kind == "semantic", ChunkEmbedding.dimension == SEMANTIC_DIMENSION),
        ).outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance).where(
            DocumentVersion.id.in_(versions), *self._eligible(), provenance.is_not(None)
        ).order_by(DocumentVersion.id.asc(), distance.asc(), DocumentChunk.ordinal.asc(), DocumentChunk.id.asc()))).all()
        per_version: dict[UUID, _Candidate] = {}
        for row in rows:
            per_version.setdefault(row[1], _Candidate(row[0], row[1], row[2], row[3], float(row[4]), ("metadata",)))
        return tuple(per_version[version] for version in versions if version in per_version)

    @staticmethod
    def _rrf(
        semantic: tuple[_Candidate, ...], supported: tuple[_Candidate, ...], numbers: tuple[UUID, ...], titles: tuple[UUID, ...]
    ) -> tuple[_Candidate, ...]:
        arms: tuple[tuple[str, tuple[UUID, ...]], ...] = (
            ("semantic", tuple(item.version_id for item in semantic)), ("identity", numbers), ("title", titles),
        )
        by_version = {item.version_id: item for item in (*semantic, *supported)}
        scores: dict[UUID, float] = {}
        contribution: dict[UUID, set[str]] = {}
        for arm, versions in arms:
            for rank, version_id in enumerate(versions, 1):
                if version_id not in by_version:
                    continue
                scores[version_id] = scores.get(version_id, 0.0) + 1 / (_RRF_K + rank)
                contribution.setdefault(version_id, set()).add(arm)
        return tuple(
            replace(by_version[version], arms=tuple(sorted(contribution[version])))
            for version in sorted(scores, key=lambda item: (-scores[item], by_version[item].ordinal, item))
        )

    async def _hydrate(self, session: AsyncSession, candidates: tuple[_Candidate, ...]) -> tuple[_Candidate, ...]:
        needed: dict[UUID, set[int]] = {}
        for item in candidates:
            needed.setdefault(item.version_id, set()).update((max(0, item.ordinal - 1), item.ordinal, item.ordinal + 1))
        predicates = [and_(DocumentChunk.document_version_id == key, DocumentChunk.ordinal.in_(ordinals)) for key, ordinals in needed.items()]
        rows = (await session.execute(select(
            DocumentChunk.document_version_id, DocumentChunk.ordinal, DocumentChunk.content_text, DocumentChunk.locator
        ).where(or_(*predicates)))).all() if predicates else ()
        texts = {(row[0], row[1]): (row[2], row[3]) for row in rows}
        result: list[_Candidate] = []
        for item in candidates:
            current = texts.get((item.version_id, item.ordinal))
            if current is None:
                continue
            before = texts.get((item.version_id, item.ordinal - 1), ("", None))[0][-_CONTEXT:]
            after = texts.get((item.version_id, item.ordinal + 1), ("", None))[0][:_CONTEXT]
            label = str(current[1].get("label", "")).strip() if isinstance(current[1], dict) else ""
            result.append(replace(item, text="\n".join(x for x in (label, before, current[0], after) if x)[:_HYDRATED_MAX]))
        return tuple(result)

    async def _rerank(self, request: RetrievalRequest, candidates: tuple[_Candidate, ...]) -> tuple[tuple[_Candidate, ...], bool]:
        payload = RerankRequest(query=request.query, candidates=tuple(RerankCandidate(chunk_id=str(x.chunk_id), text=x.text) for x in candidates))
        try:
            result = await asyncio.wait_for(self._reranker.rerank(payload), timeout=self._timeout_seconds)
            expected = tuple(str(item.chunk_id) for item in candidates)
            if result.candidate_ids != expected or len(result.scores) != len(candidates):
                raise ValueError("invalid alignment")
            if not all(isinstance(score, (float, int)) and isfinite(score) for score in result.scores):
                raise ValueError("invalid score")
            ranked = tuple(
                replace(item, reranker_score=float(score))
                for item, score in zip(candidates, result.scores, strict=True)
            )
            return tuple(sorted(ranked, key=lambda x: (-(x.reranker_score or 0.0), x.ordinal, x.chunk_id))), False
        except Exception:
            return candidates, True

    async def _write(self, request: RetrievalRequest, candidates: tuple[_Candidate, ...], fallback: bool, diagnostics: MetadataRepairDiagnostics) -> RetrievalResult:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                valid = await self._revalidate(session, candidates)
                selected = valid[:request.top_k]
                version = "v6_semantic_exact_metadata_reranker_fallback" if fallback else "v6_semantic_exact_metadata_reranked"
                result = await self._persist(session, request, selected, version, RetrievalDecision.EVIDENCE_AVAILABLE if selected else RetrievalDecision.NO_RESULTS, RetrievalReason.SEMANTIC_EVIDENCE_AVAILABLE if selected else RetrievalReason.NO_SEMANTIC_MATCH)
        rejections = dict(diagnostics.rejection_reason_counts)
        if fallback:
            rejections["FINAL_TOP_K_CUTOFF"] = max(0, len(valid) - len(selected))
        elif not rejections.get("RERANK_DEMOTION"):
            rejections["FINAL_TOP_K_CUTOFF"] = max(0, len(valid) - len(selected))
        self._emit(
            replace(diagnostics, rejection_reason_counts=rejections),
            final_count=len({x.version_id for x in selected}),
            fallback=fallback,
            version=version,
        )
        return result

    async def _revalidate(self, session: AsyncSession, candidates: tuple[_Candidate, ...]) -> tuple[_Candidate, ...]:
        ids = tuple(item.chunk_id for item in candidates)
        if not ids:
            return ()
        provenance = self._provenance_id()
        valid_rows = (await session.execute(select(DocumentChunk.id, DocumentChunk.document_version_id, SourceProvenanceRecord.id).select_from(DocumentChunk).join(DocumentVersion).join(LegalDocument).join(ChunkEmbedding, and_(ChunkEmbedding.document_chunk_id == DocumentChunk.id, ChunkEmbedding.embedding_model_id == SEMANTIC_PROFILE_ID, ChunkEmbedding.embedding_kind == "semantic", ChunkEmbedding.dimension == SEMANTIC_DIMENSION)).outerjoin(SourceProvenanceRecord, SourceProvenanceRecord.id == provenance).where(DocumentChunk.id.in_(ids), *self._eligible(), provenance.is_not(None)))).all()
        valid = {(row[0], row[1], row[2]) for row in valid_rows}
        return tuple(item for item in candidates if (item.chunk_id, item.version_id, item.provenance_id) in valid)

    async def _persist(self, session: AsyncSession, request: RetrievalRequest, candidates: tuple[_Candidate, ...], version: str, decision: RetrievalDecision, reason: RetrievalReason) -> RetrievalResult:
        run = RetrievalRun(id=uuid4(), strategy="postgresql_semantic", strategy_version=version, scope=RetrievalScope.LATEST_INGESTED.value, trust_scope=request.trust_scope.value, query_max_chars=QUERY_MAX_CHARS, top_k=request.top_k, candidate_count=len(candidates), citation_count=len(candidates), evidence_decision=decision.value, evidence_reason=reason.value)
        session.add(run)
        await session.flush()
        output = []
        for rank, item in enumerate(candidates, 1):
            citation_id = uuid4()
            session.add(CitationRecord(id=citation_id, retrieval_run_id=run.id, document_chunk_id=item.chunk_id, source_provenance_record_id=item.provenance_id, rank=rank, lexical_score=None, semantic_score=item.semantic_score, reranker_score=item.reranker_score))
            output.append(RetrievalCandidate(citation_id=citation_id, document_chunk_id=item.chunk_id, rank=rank, lexical_score=None, semantic_score=item.semantic_score, reranker_score=item.reranker_score))
        return RetrievalResult(retrieval_run_id=run.id, candidates=tuple(output), candidate_count=len(output), citation_count=len(output), decision=decision, reason=reason)

    @staticmethod
    def _diagnostics(version: str, **counts: int) -> MetadataRepairDiagnostics:
        return MetadataRepairDiagnostics(version, counts.get("semantic", 0), counts.get("identity", 0), counts.get("title", 0), counts.get("ambiguous", 0), counts.get("unsupported", 0), counts.get("pre", 0), counts.get("post", 0), counts.get("reranker", 0), 0, False, {}, {})

    @staticmethod
    def _rerank_demotion(
        original: tuple[_Candidate, ...], reranked: tuple[_Candidate, ...], top_k: int
    ) -> int:
        before = {item.version_id for item in original[:top_k]}
        after = {item.version_id for item in reranked[:top_k]}
        return len(before - after)

    @staticmethod
    def _rejection_counts(
        *,
        document_collapse: int = 0,
        semantic_rank_cutoff: int = 0,
        duplicate_chunk: int = 0,
        ambiguous: int = 0,
        unsupported: int = 0,
    ) -> dict[str, int]:
        return {
            "DOCUMENT_VERSION_COLLAPSE": max(0, document_collapse),
            "SEMANTIC_RANK_CUTOFF": max(0, semantic_rank_cutoff),
            "DUPLICATE_CHUNK": max(0, duplicate_chunk),
            "RERANK_DEMOTION": 0,
            "FINAL_TOP_K_CUTOFF": 0,
            "IDENTITY_AMBIGUOUS": max(0, ambiguous),
            "METADATA_ONLY_NO_SUPPORTING_CHUNK": max(0, unsupported),
        }

    def _emit(self, diagnostics: MetadataRepairDiagnostics, *, final_count: int, fallback: bool, version: str | None = None) -> None:
        if self._observer is None:
            return
        self._observer(replace(diagnostics, strategy_version=version or diagnostics.strategy_version, final_count=final_count, reranker_fallback=fallback))
