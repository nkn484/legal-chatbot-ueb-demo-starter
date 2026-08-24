import json
from uuid import UUID, uuid5

import pytest

from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    DocumentIdentity,
    LaneObservation,
    ProvenanceType,
    RetrievalLane,
    SourceId,
    SourceScopeObservation,
)
from legal_chatbot.retrieval.quality_repair.ranking import (
    RRF_K,
    ChunkMergeResult,
    LaneDocumentPool,
    PoolMeasurementSummary,
    PoolReferenceSummary,
    PoolSelectionStatus,
    RankingRejectionCode,
    build_lane_document_pool,
    fused_diagnostic_top50,
    fused_pool,
    lane_unique_contributions,
    merge_chunk_candidates,
    select_final_top3,
    select_pareto_pool,
)


def _uuid(name: str) -> UUID:
    return uuid5(UUID("12345678-1234-5678-1234-567812345678"), name)


def _identity(
    name: str, *, version: str | None = None, provenance: str = "provenance"
) -> DocumentIdentity:
    return DocumentIdentity(
        document_id=_uuid(f"document-{name}"),
        document_version_id=_uuid(f"version-{version or name}"),
        source_id=SourceId.VBQPPL,
        external_id=f"private-external-{name}",
        document_number_normalized=f"private-number-{name}",
        title=f"private-title-{name}",
        version_number=1,
        provenance_record_id=_uuid(f"{provenance}-{name}"),
        provenance_type=ProvenanceType.SOURCE_FETCH,
        latest_ingested=True,
    )


def _candidate(
    name: str,
    identity: DocumentIdentity,
    lane: RetrievalLane,
    rank: int,
    *,
    score: float | None = 1.0,
    ordinal: int = 0,
    unit_id: str | None = None,
    supporting_semantic_score: float | None = None,
) -> CandidateEvidence:
    return CandidateEvidence(
        chunk_id=_uuid(f"chunk-{name}"),
        identity=identity,
        ordinal=ordinal,
        observations=(
            LaneObservation(
                lane=lane,
                rank=rank,
                score=score,
                query_count=1,
                elapsed_ms=1,
                rows_returned=1,
            ),
        ),
        unit_ids=() if unit_id is None else (unit_id,),
        supporting_semantic_score=supporting_semantic_score,
        source_scope=SourceScopeObservation.NONE,
        eligible=True,
    )


def _rejection_count(
    result: ChunkMergeResult | LaneDocumentPool, code: RankingRejectionCode
) -> int:
    counts = result.diagnostics.rejection_counts
    return next((item.count for item in counts if item.code is code), 0)


def test_merge_combines_independent_lanes_and_preserves_opaque_unit_tags() -> None:
    identity = _identity("merge")
    semantic = _candidate(
        "same",
        identity,
        RetrievalLane.SEMANTIC,
        2,
        unit_id="unit-semantic",
        supporting_semantic_score=0.123456789,
    )
    title = _candidate("same", identity, RetrievalLane.TITLE_FTS, 1, unit_id="unit-title")
    merged = merge_chunk_candidates((title, semantic))

    assert len(merged.candidates) == 1
    candidate = merged.candidates[0]
    assert {observation.lane for observation in candidate.observations} == {
        RetrievalLane.SEMANTIC,
        RetrievalLane.TITLE_FTS,
    }
    assert candidate.unit_ids == ("unit-semantic", "unit-title")
    assert candidate.supporting_semantic_score == pytest.approx(0.123456789)
    assert _rejection_count(merged, RankingRejectionCode.DUPLICATE_CHUNK) == 1
    assert "0.123456789" not in json.dumps(candidate.model_dump(mode="json"))
    assert "0.123456789" not in repr(candidate)
    near_score = title.model_copy(update={"supporting_semantic_score": 0.1234567895})
    near_merged = merge_chunk_candidates((semantic, near_score))
    assert near_merged.candidates[0].supporting_semantic_score == 0.123456789

    conflicting = title.model_copy(update={"identity": _identity("merge", provenance="other")})
    with pytest.raises(ValueError, match="fully agree"):
        merge_chunk_candidates((semantic, conflicting))
    conflicting_score = title.model_copy(update={"supporting_semantic_score": 0.5})
    with pytest.raises(ValueError, match="supporting semantic"):
        merge_chunk_candidates((semantic, conflicting_score))


def test_lane_collapse_is_version_isolated_and_deterministic_before_cutoff() -> None:
    first = _identity("first")
    second = _identity("second")
    same_version_other_identity = _identity("other", version="first")
    candidates = (
        _candidate("first-a", first, RetrievalLane.SEMANTIC, 1, score=0.2, ordinal=2),
        _candidate("first-b", first, RetrievalLane.SEMANTIC, 1, score=0.9, ordinal=3),
        _candidate("second", second, RetrievalLane.SEMANTIC, 2, ordinal=0),
    )
    pool = build_lane_document_pool(candidates, RetrievalLane.SEMANTIC, 8)
    assert len(pool.candidates) == 2
    assert pool.candidates[0].representative.chunk_id == _uuid("chunk-first-b")
    assert pool.candidates[0].supporting_chunk_count == 1
    assert pool.diagnostics.duplicates_collapsed == 1
    assert _rejection_count(pool, RankingRejectionCode.DOCUMENT_VERSION_COLLAPSE) == 1
    assert pool.candidates[0].merged_unit_ids == ()
    assert build_lane_document_pool(tuple(reversed(candidates)), RetrievalLane.SEMANTIC, 8) == pool
    with pytest.raises(ValueError, match="different identities"):
        build_lane_document_pool(
            (
                candidates[0],
                _candidate("conflict", same_version_other_identity, RetrievalLane.SEMANTIC, 3),
            ),
            RetrievalLane.SEMANTIC,
            8,
        )


def test_lane_collapse_breaks_equal_rank_and_score_ties_by_ordinal_then_chunk_id() -> None:
    identity = _identity("tie")
    later = _candidate("tie-later", identity, RetrievalLane.SEMANTIC, 3, score=0.5, ordinal=2)
    earlier = _candidate("tie-earlier", identity, RetrievalLane.SEMANTIC, 3, score=0.5, ordinal=1)
    pool = build_lane_document_pool((later, earlier), RetrievalLane.SEMANTIC, 8)
    assert pool.candidates[0].representative.ordinal == 1
    assert build_lane_document_pool((earlier, later), RetrievalLane.SEMANTIC, 8) == pool


@pytest.mark.parametrize("pool_size", (8, 12, 16, 20, 50))
def test_lane_pool_accepts_release_and_diagnostic_sizes(pool_size: int) -> None:
    candidates = tuple(
        _candidate(f"pool-{index}", _identity(f"pool-{index}"), RetrievalLane.SEMANTIC, index + 1)
        for index in range(21)
    )
    pool = build_lane_document_pool(candidates, RetrievalLane.SEMANTIC, pool_size)
    assert len(pool.candidates) == min(pool_size, 21)
    assert pool.diagnostics.pool_cutoff_count == max(21 - pool_size, 0)
    if pool_size < 50:
        assert _rejection_count(pool, RankingRejectionCode.LANE_POOL_CUTOFF) == 21 - pool_size
    with pytest.raises(ValueError):
        build_lane_document_pool(candidates, RetrievalLane.SEMANTIC, 7)


def test_fusion_uses_equal_rrf_and_lane_alphabetical_ties_without_padding() -> None:
    shared = _identity("shared")
    other = _identity("other")
    semantic_pool = build_lane_document_pool(
        (
            _candidate("shared-semantic", shared, RetrievalLane.SEMANTIC, 1, ordinal=0),
            _candidate("other-semantic", other, RetrievalLane.SEMANTIC, 2, ordinal=0),
        ),
        RetrievalLane.SEMANTIC,
        8,
    )
    content_pool = build_lane_document_pool(
        (_candidate("shared-content", shared, RetrievalLane.CONTENT_FTS, 1, ordinal=9),),
        RetrievalLane.CONTENT_FTS,
        8,
    )
    fused = fused_pool((semantic_pool, content_pool), 8)
    shared_candidate = next(
        candidate for candidate in fused.candidates if candidate.identity == shared
    )
    assert shared_candidate.fusion_score == pytest.approx(2 / (RRF_K + 1))
    assert shared_candidate.representative.chunk_id == _uuid("chunk-shared-content")
    assert len(fused.candidates) == 2
    assert select_final_top3(fused) == fused.candidates


def test_fusion_counterfactual_contributions_are_private_and_deterministic() -> None:
    semantic_pool = build_lane_document_pool(
        (_candidate("semantic-only", _identity("semantic-only"), RetrievalLane.SEMANTIC, 1),),
        RetrievalLane.SEMANTIC,
        8,
    )
    title_pool = build_lane_document_pool(
        (_candidate("title-only", _identity("title-only"), RetrievalLane.TITLE_FTS, 1),),
        RetrievalLane.TITLE_FTS,
        8,
    )
    contributions = lane_unique_contributions((title_pool, semantic_pool), 8)
    assert [(item.lane, item.unique_count) for item in contributions] == [
        (RetrievalLane.SEMANTIC, 1),
        (RetrievalLane.TITLE_FTS, 1),
    ]
    fused = fused_pool((semantic_pool, title_pool), 8).model_copy(
        update={"lane_unique_contributions": contributions}
    )
    private_uuid = str(_uuid("version-semantic-only"))
    assert private_uuid not in json.dumps(fused.model_dump(mode="json"))
    assert private_uuid not in repr(fused)
    assert private_uuid not in json.dumps(fused.to_public_dict())


def test_diagnostic_fused_top50_is_private_ordered_and_not_final_evidence() -> None:
    candidates = tuple(
        _candidate(
            f"diagnostic-{index}",
            _identity(f"diagnostic-{index}"),
            RetrievalLane.SEMANTIC,
            index + 1,
            supporting_semantic_score=0.333333333 if index == 0 else None,
        )
        for index in range(50)
    )
    lane_pool = build_lane_document_pool(candidates, RetrievalLane.SEMANTIC, 50)
    diagnostic = fused_diagnostic_top50((lane_pool,))
    assert diagnostic.release_eligible is False
    assert len(diagnostic.candidates) == 50
    assert diagnostic.candidates[0].best_chunk_rank == 1
    assert diagnostic.candidates[0].representative.supporting_semantic_score == 0.333333333
    assert diagnostic.candidates[-1].best_chunk_rank == 50
    private_uuid = str(_uuid("version-diagnostic-0"))
    serialized = json.dumps(diagnostic.model_dump(mode="json"))
    assert private_uuid not in serialized
    assert "0.333333333" not in serialized
    assert private_uuid not in repr(diagnostic)
    with pytest.raises(TypeError, match="release FusedPool"):
        select_final_top3(diagnostic)  # type: ignore[arg-type]


def test_pareto_pool_selection_uses_smallest_eligible_pool_or_no_selection() -> None:
    reference = PoolReferenceSummary(
        candidate_identity_count=5,
        nonexpected_candidate_rate=0.10,
        p95_latency_ms=900,
        query_count=3,
        set_c_failure_count=0,
    )
    selected = select_pareto_pool(
        reference,
        (
            PoolMeasurementSummary(
                pool_size=8,
                candidate_identity_count=5,
                nonexpected_candidate_rate=0.10,
                p95_latency_ms=1000,
                query_count=3,
                set_c_failure_count=0,
            ),
            PoolMeasurementSummary(
                pool_size=12,
                candidate_identity_count=6,
                nonexpected_candidate_rate=0.12,
                p95_latency_ms=1200,
                query_count=4,
                set_c_failure_count=0,
            ),
            PoolMeasurementSummary(
                pool_size=16,
                candidate_identity_count=7,
                nonexpected_candidate_rate=0.13,
                p95_latency_ms=1300,
                query_count=4,
                set_c_failure_count=0,
            ),
            PoolMeasurementSummary(
                pool_size=20,
                candidate_identity_count=7,
                nonexpected_candidate_rate=0.13,
                p95_latency_ms=1400,
                query_count=4,
                set_c_failure_count=0,
            ),
        )
    )
    assert selected.status is PoolSelectionStatus.SELECTED
    assert selected.selected_pool_size == 12
    no_selection = select_pareto_pool(
        reference,
        tuple(
            PoolMeasurementSummary(
                pool_size=pool_size,
                candidate_identity_count=5,
                nonexpected_candidate_rate=0.10,
                p95_latency_ms=1000,
                query_count=3,
                set_c_failure_count=1,
            )
            for pool_size in (8, 12, 16, 20)
        )
    )
    assert no_selection.status is PoolSelectionStatus.NO_SELECTION


def test_pareto_pool8_uses_the_reference_and_measurements_require_exact_matrix() -> None:
    reference = PoolReferenceSummary(
        candidate_identity_count=4,
        nonexpected_candidate_rate=0.10,
        p95_latency_ms=1000,
        query_count=3,
        set_c_failure_count=0,
    )
    measurements = tuple(
        PoolMeasurementSummary(
            pool_size=pool_size,
            candidate_identity_count=5,
            nonexpected_candidate_rate=0.10,
            p95_latency_ms=1100,
            query_count=3,
            set_c_failure_count=0,
        )
        for pool_size in (8, 12, 16, 20)
    )
    selection = select_pareto_pool(reference, measurements)
    assert selection.selected_pool_size == 8
    assert "document" not in json.dumps(reference.model_dump(mode="json"))
    assert "document" not in repr(reference)
    with pytest.raises(ValueError, match="exactly the four"):
        select_pareto_pool(reference, measurements[:3])
    with pytest.raises(ValueError, match="exactly the four"):
        select_pareto_pool(reference, measurements[:3] + (measurements[0],))
