"""Unit coverage for bounded concept-aware candidate retrieval orchestration."""

from __future__ import annotations

from uuid import UUID, uuid5

import pytest

from legal_chatbot.documents.quality_candidate_reader import (
    FTSQueryMode,
    QualityCandidateReadResult,
)
from legal_chatbot.documents.quality_retrieval_pipeline import LegalQualityCandidatePipeline
from legal_chatbot.documents.quality_retrieval_repository import PostgresQualityRetrievalRepository
from legal_chatbot.retrieval.quality_repair.analyzer import LegalQuestionAnalyzer
from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    CollapsedDocumentCandidate,
    DocumentIdentity,
    LaneAggregate,
    LaneObservation,
    ProvenanceType,
    RetrievalLane,
    SourceId,
    SourceScopeObservation,
)
from legal_chatbot.retrieval.quality_repair.strategy import materialize_strategy
from legal_chatbot.semantic.models import SemanticEmbeddingBatch


def _uuid(value: str) -> UUID:
    return uuid5(UUID("12345678-1234-5678-1234-567812345678"), value)


def _candidate(index: int) -> CandidateEvidence:
    identity = DocumentIdentity(
        document_id=_uuid(f"document-{index}"),
        document_version_id=_uuid(f"version-{index}"),
        source_id=SourceId.VBQPPL,
        external_id=f"external-{index}",
        version_number=1,
        provenance_record_id=_uuid(f"provenance-{index}"),
        provenance_type=ProvenanceType.SOURCE_FETCH,
        latest_ingested=True,
    )
    return CandidateEvidence(
        chunk_id=_uuid(f"chunk-{index}"),
        identity=identity,
        ordinal=index,
        observations=(
            LaneObservation(
                lane=RetrievalLane.SEMANTIC,
                rank=1,
                score=0.9,
                query_count=1,
                elapsed_ms=1,
                rows_returned=1,
            ),
        ),
        source_scope=SourceScopeObservation.NONE,
        eligible=True,
    )


def _read_result(candidates: tuple[CandidateEvidence, ...]) -> QualityCandidateReadResult:
    return QualityCandidateReadResult(
        lane_candidates={
            RetrievalLane.SEMANTIC: candidates,
            RetrievalLane.CONTENT_FTS: (),
            RetrievalLane.TITLE_FTS: (),
        },
        lane_metrics=(),
        data_query_count=1,
        explain_query_count=0,
        query_count=1,
        transaction_elapsed_ms=1,
        requested_fts_query_mode=FTSQueryMode.BOUNDED_OR,
        applied_fts_query_mode=FTSQueryMode.BOUNDED_OR,
        fts_preparation_query_count=1,
        fts_preparation_elapsed_ms=1,
        bounded_or_selected_lexeme_count=1,
        bounded_or_source_lexeme_count=1,
    )


class _Embedder:
    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        del text
        return SemanticEmbeddingBatch(vectors=((1.0, *(0.0 for _ in range(383))),))


class _Reader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...], FTSQueryMode | str]] = []

    async def read_candidates(
        self,
        question: str,
        active_source_ids: tuple[str, ...],
        query_vector: tuple[float, ...],
        diagnostic_limit: int = 50,
        explain: bool = False,
        fts_query_mode: FTSQueryMode | str = FTSQueryMode.NATURAL,
    ) -> QualityCandidateReadResult:
        del query_vector, diagnostic_limit, explain
        self.calls.append((question, active_source_ids, fts_query_mode))
        # The first unit and the one repair unit obtain evidence. The final unit
        # remains unresolved, proving the pipeline cannot loop repairs.
        index = len(self.calls)
        return _read_result((_candidate(index),) if index in (1, 4) else ())


async def test_pipeline_uses_unit_concepts_and_executes_exactly_one_repair() -> None:
    reader = _Reader()
    pipeline = LegalQualityCandidatePipeline(
        reader,
        _Embedder(),  # type: ignore[arg-type]
        materialize_strategy("quality_retrieval_evidence_repair_v1", 8),
        (SourceId.VBQPPL,),
    )
    analysis = LegalQuestionAnalyzer().analyze(
        "Thủ tục đăng ký bảo hiểm là gì; sau đó nộp hồ sơ ở đâu; rồi khiếu nại thế nào?"
    )

    result = await pipeline.retrieve(analysis)

    assert result.reader_call_count == 4
    assert result.repair_executed is True
    assert len(reader.calls) == 4
    assert all(sources == ("VBQPPL",) for _, sources, _ in reader.calls)
    assert all(mode is FTSQueryMode.BOUNDED_OR for _, _, mode in reader.calls)
    assert len(result.selection.candidates) == 2
    assert result.coverage.unresolved_unit_ids == ("u03",)


def test_persistence_adapter_rejects_invalid_score_contracts_before_writing() -> None:
    evidence = _candidate(1)
    collapsed = CollapsedDocumentCandidate(
        identity=evidence.identity,
        representative=evidence,
        supporting_chunk_count=0,
        best_chunk_rank=1,
        best_chunk_score=0.9,
        lane_aggregates=(
            LaneAggregate(lane=RetrievalLane.SEMANTIC, best_rank=1, best_score=2.0),
        ),
        merged_unit_ids=("u01",),
    )

    with pytest.raises(ValueError, match="semantic score"):
        PostgresQualityRetrievalRepository._selected(collapsed)
