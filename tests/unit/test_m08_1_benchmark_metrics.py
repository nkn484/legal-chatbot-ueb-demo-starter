"""Deterministic unit coverage for content-free M08.1 benchmark metrics."""

from dataclasses import asdict
from uuid import UUID

import pytest

from legal_chatbot.retrieval.benchmark_metrics import (
    MAX_BENCHMARK_K,
    BenchmarkMode,
    BenchmarkObservation,
    FallbackKind,
    aggregate_benchmark_metrics,
    compare_benchmark_modes,
)
from legal_chatbot.retrieval.models import RetrievalDecision


def _id(value: int) -> UUID:
    return UUID(int=value)


def _observation(
    case: int,
    *,
    mode: BenchmarkMode = BenchmarkMode.PLANNED,
    ranked: tuple[int, ...] = (),
    gold: frozenset[int] = frozenset(),
    decision: RetrievalDecision = RetrievalDecision.EVIDENCE_AVAILABLE,
    wrong_scope: bool = False,
    anchor_drift: bool = False,
    planner_latency_ms: float | None = None,
    end_to_end_latency_ms: float = 10.0,
    fallback_kind: FallbackKind = FallbackKind.NONE,
) -> BenchmarkObservation:
    return BenchmarkObservation(
        case_id=_id(case),
        mode=mode,
        ranked_document_chunk_ids=tuple(_id(value) for value in ranked),
        gold_document_chunk_ids=frozenset(_id(value) for value in gold),
        decision=decision,
        wrong_scope=wrong_scope,
        anchor_drift=anchor_drift,
        planner_latency_ms=planner_latency_ms,
        end_to_end_latency_ms=end_to_end_latency_ms,
        fallback_kind=fallback_kind,
    )


def test_aggregate_calculates_macro_relevance_rates_scope_drift_and_split_fallbacks() -> None:
    observations = (
        _observation(
            1,
            ranked=(10, 20),
            gold=frozenset((10, 30)),
            wrong_scope=True,
            planner_latency_ms=10,
            end_to_end_latency_ms=110,
            fallback_kind=FallbackKind.EXPECTED_INJECTED,
        ),
        _observation(
            2,
            ranked=(40,),
            gold=frozenset((50,)),
            anchor_drift=True,
            planner_latency_ms=20,
            end_to_end_latency_ms=120,
            fallback_kind=FallbackKind.UNEXPECTED_RUNTIME,
        ),
        _observation(
            3,
            decision=RetrievalDecision.NO_RESULTS,
            planner_latency_ms=30,
            end_to_end_latency_ms=130,
        ),
    )

    metrics = aggregate_benchmark_metrics(observations, k=2)

    assert metrics.case_count == 3
    assert metrics.gold_case_count == 2
    assert metrics.hit_at_k == 0.5
    assert metrics.recall_at_k == 0.25
    assert metrics.mrr == 0.5
    assert metrics.no_results_rate == pytest.approx(1 / 3)
    assert metrics.wrong_scope_rate == pytest.approx(1 / 3)
    assert metrics.anchor_drift_rate == pytest.approx(1 / 3)
    assert metrics.planner_latency_p50_ms == 20
    assert metrics.planner_latency_p95_ms == 30
    assert metrics.mean_end_to_end_latency_ms == 120
    assert metrics.fallback_rate == pytest.approx(2 / 3)
    assert metrics.expected_injected_fallback_rate == pytest.approx(1 / 3)
    assert metrics.unexpected_runtime_fallback_rate == pytest.approx(1 / 3)


def test_metrics_exclude_empty_gold_sets_and_handle_all_zero_denominators() -> None:
    metrics = aggregate_benchmark_metrics((), k=1)
    assert metrics.case_count == metrics.gold_case_count == 0
    assert all(value == 0.0 for value in asdict(metrics).values() if isinstance(value, float))

    no_match = _observation(1, decision=RetrievalDecision.NO_RESULTS)
    no_match_metrics = aggregate_benchmark_metrics((no_match,), k=1)
    assert no_match_metrics.gold_case_count == 0
    assert no_match_metrics.hit_at_k == no_match_metrics.recall_at_k == no_match_metrics.mrr == 0.0


def test_k_bounds_duplicate_ranked_ids_and_invalid_no_results_are_rejected() -> None:
    valid = _observation(1, ranked=(1,), gold=frozenset((1,)))
    for k in (0, MAX_BENCHMARK_K + 1, True):
        with pytest.raises(ValueError, match="k must"):
            aggregate_benchmark_metrics((valid,), k=k)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        _observation(1, ranked=(1, 1))
    with pytest.raises(ValueError, match="no-evidence"):
        _observation(1, ranked=(1,), decision=RetrievalDecision.NO_RESULTS)


def test_percentiles_use_deterministic_nearest_rank_and_comparison_returns_latency_delta() -> None:
    raw = (
        _observation(
            1,
            mode=BenchmarkMode.RAW,
            ranked=(10,),
            gold=frozenset((10,)),
            end_to_end_latency_ms=10,
        ),
        _observation(
            2,
            mode=BenchmarkMode.RAW,
            decision=RetrievalDecision.NO_RESULTS,
            end_to_end_latency_ms=20,
        ),
    )
    planned = (
        _observation(
            1,
            ranked=(10,),
            gold=frozenset((10,)),
            planner_latency_ms=1,
            end_to_end_latency_ms=15,
        ),
        _observation(
            2,
            decision=RetrievalDecision.NO_RESULTS,
            planner_latency_ms=2,
            end_to_end_latency_ms=25,
        ),
    )

    comparison = compare_benchmark_modes(raw, planned, k=1)

    assert comparison.matched_case_count == 2
    assert comparison.planned.planner_latency_p50_ms == 1
    assert comparison.planned.planner_latency_p95_ms == 2
    assert comparison.end_to_end_latency_delta_ms == 5
    with pytest.raises(ValueError, match="identical case IDs"):
        compare_benchmark_modes(
            raw,
            (_observation(3, decision=RetrievalDecision.NO_RESULTS),),
            k=1,
        )
