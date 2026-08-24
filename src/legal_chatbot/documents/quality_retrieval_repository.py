"""Opt-in persistence adapter for the quality candidate pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import CitationRecord, RetrievalRun
from legal_chatbot.documents.quality_retrieval_pipeline import LegalQualityCandidatePipeline
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
from legal_chatbot.retrieval.quality_repair.analyzer import LegalQuestionAnalyzer
from legal_chatbot.retrieval.quality_repair.models import CollapsedDocumentCandidate, RetrievalLane
from legal_chatbot.retrieval.quality_repair.strategy import QUALITY_STRATEGY_VERSION

_STRATEGY = "quality_retrieval"


@dataclass(frozen=True)
class _SelectedCandidate:
    chunk_id: UUID
    version_id: UUID
    provenance_id: UUID
    provenance_version_id: UUID
    lexical_score: float | None
    semantic_score: float | None


class PostgresQualityRetrievalRepository:
    """Persist exactly the generalized, selected evidence from one quality pipeline run."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        analyzer: LegalQuestionAnalyzer,
        pipeline: LegalQualityCandidatePipeline,
    ) -> None:
        self._session_factory = session_factory
        self._analyzer = analyzer
        self._pipeline = pipeline

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        """Run quality retrieval without persisting query or repair text."""

        try:
            execution = await self._pipeline.retrieve(self._analyzer.analyze(request.query))
            candidates = tuple(
                self._selected(candidate) for candidate in execution.selection.candidates
            )
            if len(candidates) > request.top_k:
                raise ValueError("quality selection exceeds retrieval evidence bound")
            async with self._session_factory() as session:
                async with session.begin():
                    result = await self._persist(session, request, candidates)
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE) from None
        return result.model_copy(update={"quality_context": execution.to_context()})

    async def persist_zero_evidence_run(
        self,
        request: RetrievalRequest,
        decision: RetrievalDecision,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        """Persist the existing fail-closed zero-evidence decision without analysis."""

        try:
            async with self._session_factory() as session:
                async with session.begin():
                    return await self._persist(
                        session, request, (), decision=decision, reason=reason
                    )
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE) from None

    @staticmethod
    def _selected(candidate: CollapsedDocumentCandidate) -> _SelectedCandidate:
        aggregates = {
            aggregate.lane: aggregate.best_score for aggregate in candidate.lane_aggregates
        }
        semantic_score = aggregates.get(RetrievalLane.SEMANTIC)
        lexical_scores = tuple(
            score
            for lane, score in aggregates.items()
            if lane in (RetrievalLane.CONTENT_FTS, RetrievalLane.TITLE_FTS) and score is not None
        )
        lexical_score = max(lexical_scores) if lexical_scores else None
        if semantic_score is not None and not -1 <= semantic_score <= 1:
            raise ValueError("semantic score is outside its persisted contract")
        if lexical_score is not None and lexical_score < 0:
            raise ValueError("lexical score is outside its persisted contract")
        if lexical_score is None and semantic_score is None:
            raise ValueError("selected evidence requires one retrieval score")
        identity = candidate.identity
        return _SelectedCandidate(
            chunk_id=candidate.representative.chunk_id,
            version_id=identity.document_version_id,
            provenance_id=identity.provenance_record_id,
            provenance_version_id=identity.document_version_id,
            lexical_score=lexical_score,
            semantic_score=semantic_score,
        )

    @staticmethod
    async def _persist(
        session: AsyncSession,
        request: RetrievalRequest,
        candidates: tuple[_SelectedCandidate, ...],
        *,
        decision: RetrievalDecision | None = None,
        reason: RetrievalReason | None = None,
    ) -> RetrievalResult:
        if any(candidate.provenance_version_id != candidate.version_id for candidate in candidates):
            decision = RetrievalDecision.INVALID_EVIDENCE_CHAIN
            reason = RetrievalReason.INVALID_EVIDENCE_CHAIN
            candidates = ()
        if decision is None:
            decision = (
                RetrievalDecision.EVIDENCE_AVAILABLE if candidates else RetrievalDecision.NO_RESULTS
            )
        if reason is None:
            reason = (
                RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE
                if candidates
                else RetrievalReason.NO_LEXICAL_MATCH
            )
        run = RetrievalRun(
            id=uuid4(),
            strategy=_STRATEGY,
            strategy_version=QUALITY_STRATEGY_VERSION,
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
                )
            )
            output.append(
                RetrievalCandidate(
                    citation_id=citation_id,
                    document_chunk_id=candidate.chunk_id,
                    rank=rank,
                    lexical_score=candidate.lexical_score,
                    semantic_score=candidate.semantic_score,
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
