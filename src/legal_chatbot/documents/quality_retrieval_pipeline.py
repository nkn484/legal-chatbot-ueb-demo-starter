"""Opt-in adapter pipeline for concept-aware legal quality candidate retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Protocol

from pydantic import Field

from legal_chatbot.documents.quality_candidate_reader import (
    FTSQueryMode,
    QualityCandidateReadResult,
)
from legal_chatbot.retrieval.quality_repair.analyzer import AnalyzerObservation, AnalyzerUnit
from legal_chatbot.retrieval.quality_repair.coverage import (
    EvidenceCoverageMatrix,
    build_coverage_matrix,
)
from legal_chatbot.retrieval.quality_repair.evidence_budget import (
    EvidenceSelection,
    select_evidence,
)
from legal_chatbot.retrieval.quality_repair.evidence_pack import QualityRetrievalContext
from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    RetrievalLane,
    SourceBinding,
    SourceId,
    SourceScopeObservation,
    _FrozenContract,
)
from legal_chatbot.retrieval.quality_repair.ranking import (
    build_lane_document_pool,
    fused_pool,
    merge_chunk_candidates,
)
from legal_chatbot.retrieval.quality_repair.repair import TargetedRepairPlan, plan_targeted_repair
from legal_chatbot.retrieval.quality_repair.strategy import MaterializedQualityRepairStrategy
from legal_chatbot.semantic.models import SemanticEmbeddingBatch
from legal_chatbot.semantic.ports import SemanticEmbeddingPort

_MAX_UNIT_TERMS = 12


class QualityCandidateReaderPort(Protocol):
    """Read-only adapter contract; it never accepts an oracle or provider output."""

    async def read_candidates(
        self,
        question: str,
        active_source_ids: tuple[str, ...],
        query_vector: tuple[float, ...],
        diagnostic_limit: int = 50,
        explain: bool = False,
        fts_query_mode: FTSQueryMode | str = FTSQueryMode.NATURAL,
    ) -> QualityCandidateReadResult:
        ...


class QualityCandidatePipelineResult(_FrozenContract):
    """Private quality-retrieval state retained only through one answer request."""

    analysis: AnalyzerObservation = Field(exclude=True, repr=False)
    selection: EvidenceSelection
    coverage: EvidenceCoverageMatrix
    repair_plan: TargetedRepairPlan | None = Field(default=None, exclude=True, repr=False)
    repair_executed: bool
    reader_call_count: int = Field(ge=0, le=5)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "analysis": self.analysis.to_public_dict(),
            "selection": self.selection.to_public_dict(),
            "coverage": self.coverage.to_public_dict(),
            "repair_executed": self.repair_executed,
            "reader_call_count": self.reader_call_count,
        }

    def to_context(self) -> QualityRetrievalContext:
        return QualityRetrievalContext(
            analysis=self.analysis,
            selection=self.selection,
            coverage=self.coverage,
            repair_executed=self.repair_executed,
        )


def _query_text(unit: AnalyzerUnit) -> str | None:
    """Build one bounded memory-only retrieval unit, never a long natural conjunction."""

    concepts = unit.concept_query
    values = (
        *concepts.document_number_tokens,
        *concepts.important_noun_phrases,
        *concepts.safe_aliases,
        *concepts.core_concepts,
    )
    terms: list[str] = []
    for value in values:
        if value not in terms:
            terms.append(value)
        if len(terms) == _MAX_UNIT_TERMS:
            break
    return " ".join(terms) if terms else None


def _active_sources_for_unit(
    unit: AnalyzerUnit, active_source_ids: tuple[SourceId, ...]
) -> tuple[SourceId, ...]:
    if unit.source_binding in (SourceBinding.UNKNOWN, SourceBinding.AMBIGUOUS):
        return active_source_ids
    source_id = SourceId(unit.source_binding.value)
    return (source_id,) if source_id in active_source_ids else ()


def _annotate(candidate: CandidateEvidence, unit_id: str) -> CandidateEvidence:
    """Add an opaque unit tag while retaining the reader's immutable document identity."""

    return candidate.model_copy(
        update={"unit_ids": (unit_id,), "source_scope": SourceScopeObservation.NONE}
    )


def _best_same_lane(candidates: Iterable[CandidateEvidence]) -> tuple[CandidateEvidence, ...]:
    """Coalesce repeated unit reads before strict cross-lane merging."""

    grouped: dict[tuple[object, RetrievalLane], list[CandidateEvidence]] = defaultdict(list)
    for candidate in candidates:
        if len(candidate.observations) != 1:
            raise ValueError("reader candidates must have exactly one lane observation")
        grouped[(candidate.chunk_id, candidate.observations[0].lane)].append(candidate)
    merged: list[CandidateEvidence] = []
    for _, group in sorted(grouped.items(), key=lambda item: (str(item[0][0]), item[0][1].value)):
        first = group[0]
        if any(
            candidate.identity != first.identity
            or candidate.ordinal != first.ordinal
            or candidate.eligible != first.eligible
            for candidate in group[1:]
        ):
            raise ValueError("same reader candidate must retain one immutable identity")
        representative = min(
            group,
            key=lambda candidate: (
                candidate.observations[0].rank,
                -(candidate.observations[0].score or 0.0),
            ),
        )
        unit_ids = tuple(sorted({unit_id for candidate in group for unit_id in candidate.unit_ids}))
        merged.append(representative.model_copy(update={"unit_ids": unit_ids}))
    return tuple(merged)


class LegalQualityCandidatePipeline:
    """Run bounded unit retrieval, coverage selection, and one optional repair pass."""

    def __init__(
        self,
        reader: QualityCandidateReaderPort,
        embedder: SemanticEmbeddingPort,
        strategy: MaterializedQualityRepairStrategy,
        active_source_ids: tuple[SourceId, ...],
    ) -> None:
        if not active_source_ids or len(active_source_ids) != len(set(active_source_ids)):
            raise ValueError("active source scope must be a unique nonempty tuple")
        self._reader = reader
        self._embedder = embedder
        self._strategy = strategy
        self._active_source_ids = active_source_ids

    async def retrieve(self, analysis: AnalyzerObservation) -> QualityCandidatePipelineResult:
        """Execute at most four unit reads plus one repair; query text remains in memory."""

        collected, reader_calls = await self._read_units(analysis.units)
        selection, coverage = self._select(analysis, collected)
        repair_plan = None
        repair_executed = False
        if self._strategy.family.repair_retrieval_enabled:
            repair_plan = plan_targeted_repair(analysis, coverage)
            if repair_plan is not None:
                repair_candidates, repair_calls = await self._read_one(
                    analysis.units, repair_plan.unit_id, repair_plan.query_text
                )
                collected = (*collected, *repair_candidates)
                reader_calls += repair_calls
                selection, coverage = self._select(analysis, collected)
                repair_executed = True
        return QualityCandidatePipelineResult(
            analysis=analysis,
            selection=selection,
            coverage=coverage,
            repair_plan=repair_plan,
            repair_executed=repair_executed,
            reader_call_count=reader_calls,
        )

    async def _read_units(
        self, units: tuple[AnalyzerUnit, ...]
    ) -> tuple[tuple[CandidateEvidence, ...], int]:
        collected: list[CandidateEvidence] = []
        calls = 0
        for unit in units:
            query = _query_text(unit)
            if query is None:
                continue
            candidates, count = await self._read_one(units, unit.unit_id, query)
            collected.extend(candidates)
            calls += count
        return tuple(collected), calls

    async def _read_one(
        self, units: tuple[AnalyzerUnit, ...], unit_id: str, query: str
    ) -> tuple[tuple[CandidateEvidence, ...], int]:
        unit = next((item for item in units if item.unit_id == unit_id), None)
        if unit is None:
            raise ValueError("repair unit must belong to the original analysis")
        source_ids = _active_sources_for_unit(unit, self._active_source_ids)
        if not source_ids:
            return (), 0
        embedding = await self._embedder.embed_query(query)
        if not isinstance(embedding, SemanticEmbeddingBatch) or len(embedding.vectors) != 1:
            raise ValueError("embedder must return exactly one validated query vector")
        result = await self._reader.read_candidates(
            query,
            tuple(source.value for source in source_ids),
            embedding.vectors[0],
            diagnostic_limit=self._strategy.selected_pool,
            fts_query_mode=FTSQueryMode.BOUNDED_OR,
        )
        if not isinstance(result, QualityCandidateReadResult):
            raise ValueError("candidate reader returned an invalid result")
        candidates = tuple(
            _annotate(candidate, unit_id)
            for lane, lane_candidates in result.lane_candidates.items()
            if lane in self._strategy.family.enabled_lanes
            for candidate in lane_candidates
        )
        return candidates, 1

    def _select(
        self, analysis: AnalyzerObservation, candidates: tuple[CandidateEvidence, ...]
    ) -> tuple[EvidenceSelection, EvidenceCoverageMatrix]:
        selected_pool = self._strategy.selected_pool
        merged = merge_chunk_candidates(_best_same_lane(candidates)).candidates
        pools = tuple(
            build_lane_document_pool(merged, lane, selected_pool)
            for lane in self._strategy.family.enabled_lanes
        )
        fused = fused_pool(pools, selected_pool)
        selection = select_evidence(
            fused.candidates, analysis, dynamic=self._strategy.family.dynamic_evidence_enabled
        )
        coverage = build_coverage_matrix(
            analysis, selection, active_source_ids=self._active_source_ids
        )
        return selection, coverage
