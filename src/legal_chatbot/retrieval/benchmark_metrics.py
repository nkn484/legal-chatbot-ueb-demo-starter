"""Pure, content-free metrics for deterministic retrieval benchmark fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil, fsum, isfinite
from uuid import UUID

from legal_chatbot.retrieval.models import RetrievalDecision

MAX_BENCHMARK_K = 20


class BenchmarkMode(StrEnum):
    """Server-selected retrieval modes compared on the same fixture IDs."""

    RAW = "RAW"
    PLANNED = "PLANNED"


class FallbackKind(StrEnum):
    """Content-free fallback classifications for controlled failure fixtures."""

    NONE = "NONE"
    EXPECTED_INJECTED = "EXPECTED_INJECTED"
    UNEXPECTED_RUNTIME = "UNEXPECTED_RUNTIME"


@dataclass(frozen=True, slots=True)
class BenchmarkObservation:
    """One content-free retrieval observation for one stable benchmark fixture ID.

    ``gold_document_chunk_ids`` may be empty for a no-match fixture. ``wrong_scope``
    denotes that this result contains evidence outside the fixture's server-owned legal
    scope; ``anchor_drift`` denotes a protected-identity mismatch found by the fixture.
    Neither field contains the text used to make that determination.
    """

    case_id: UUID
    mode: BenchmarkMode
    ranked_document_chunk_ids: tuple[UUID, ...]
    gold_document_chunk_ids: frozenset[UUID]
    decision: RetrievalDecision
    wrong_scope: bool
    anchor_drift: bool
    planner_latency_ms: float | None
    end_to_end_latency_ms: float
    fallback_kind: FallbackKind = FallbackKind.NONE

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, UUID):
            raise TypeError("case_id must be a UUID")
        if not isinstance(self.mode, BenchmarkMode):
            raise TypeError("mode must be a BenchmarkMode")
        if (
            not isinstance(self.ranked_document_chunk_ids, tuple)
            or len(self.ranked_document_chunk_ids) > MAX_BENCHMARK_K
        ):
            raise ValueError(
                f"ranked_document_chunk_ids must contain at most {MAX_BENCHMARK_K} IDs"
            )
        if any(not isinstance(value, UUID) for value in self.ranked_document_chunk_ids):
            raise TypeError("ranked_document_chunk_ids must contain UUIDs")
        if len(set(self.ranked_document_chunk_ids)) != len(self.ranked_document_chunk_ids):
            raise ValueError("ranked_document_chunk_ids must be unique")
        if not isinstance(self.gold_document_chunk_ids, frozenset) or any(
            not isinstance(value, UUID) for value in self.gold_document_chunk_ids
        ):
            raise TypeError("gold_document_chunk_ids must be a frozenset of UUIDs")
        if not isinstance(self.decision, RetrievalDecision):
            raise TypeError("decision must be a RetrievalDecision")
        if (
            self.decision is RetrievalDecision.EVIDENCE_AVAILABLE
            and not self.ranked_document_chunk_ids
        ):
            raise ValueError("EVIDENCE_AVAILABLE observations require ranked IDs")
        if (
            self.decision is not RetrievalDecision.EVIDENCE_AVAILABLE
            and self.ranked_document_chunk_ids
        ):
            raise ValueError("no-evidence observations must not contain ranked IDs")
        if not isinstance(self.wrong_scope, bool) or not isinstance(self.anchor_drift, bool):
            raise TypeError("scope and anchor flags must be booleans")
        if self.planner_latency_ms is not None:
            _validate_duration(self.planner_latency_ms, "planner_latency_ms")
        _validate_duration(self.end_to_end_latency_ms, "end_to_end_latency_ms")
        if not isinstance(self.fallback_kind, FallbackKind):
            raise TypeError("fallback_kind must be a FallbackKind")


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    """Deterministic aggregate values; rates are fractions in the closed interval [0, 1]."""

    case_count: int
    gold_case_count: int
    hit_at_k: float
    recall_at_k: float
    mrr: float
    no_results_rate: float
    wrong_scope_rate: float
    anchor_drift_rate: float
    planner_latency_p50_ms: float
    planner_latency_p95_ms: float
    mean_end_to_end_latency_ms: float
    fallback_rate: float
    expected_injected_fallback_rate: float
    unexpected_runtime_fallback_rate: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.case_count, bool)
            or isinstance(self.gold_case_count, bool)
            or not isinstance(self.case_count, int)
            or not isinstance(self.gold_case_count, int)
            or not 0 <= self.gold_case_count <= self.case_count
        ):
            raise ValueError("case counts must be nonnegative and gold cases cannot exceed cases")
        for value in (
            self.hit_at_k,
            self.recall_at_k,
            self.mrr,
            self.no_results_rate,
            self.wrong_scope_rate,
            self.anchor_drift_rate,
            self.fallback_rate,
            self.expected_injected_fallback_rate,
            self.unexpected_runtime_fallback_rate,
        ):
            _validate_rate(value)
        for value in (
            self.planner_latency_p50_ms,
            self.planner_latency_p95_ms,
            self.mean_end_to_end_latency_ms,
        ):
            _validate_duration(value, "metric duration")
        if self.expected_injected_fallback_rate + self.unexpected_runtime_fallback_rate > (
            self.fallback_rate + 1e-12
        ):
            raise ValueError("split fallback rates cannot exceed total fallback rate")


@dataclass(frozen=True, slots=True)
class BenchmarkComparison:
    """Matched raw/planned aggregate metrics and planned-minus-raw mean latency."""

    raw: BenchmarkMetrics
    planned: BenchmarkMetrics
    matched_case_count: int
    end_to_end_latency_delta_ms: float

    def __post_init__(self) -> None:
        if (
            isinstance(self.matched_case_count, bool)
            or not isinstance(self.matched_case_count, int)
            or self.matched_case_count < 0
        ):
            raise ValueError("matched_case_count must be a nonnegative integer")
        if not isfinite(self.end_to_end_latency_delta_ms):
            raise ValueError("end_to_end_latency_delta_ms must be finite")


def aggregate_benchmark_metrics(
    observations: tuple[BenchmarkObservation, ...], *, k: int
) -> BenchmarkMetrics:
    """Aggregate one mode using macro Hit/Recall/MRR and nearest-rank percentiles.

    Hit@K is the fraction of non-empty-gold cases with any gold ID in the first K.
    Recall@K is the macro average of per-case retrieved-gold / gold-count. MRR is the
    macro average reciprocal first-gold rank. Empty-gold cases are excluded from all
    three relevance metrics. All rates with no denominator return ``0.0``. Percentiles
    use nearest-rank: sorted value at ``ceil(p * n) - 1``; no planner durations is 0.0.
    """

    _validate_k(k)
    _validate_unique_case_ids(observations)
    count = len(observations)
    gold_observations = tuple(
        observation for observation in observations if observation.gold_document_chunk_ids
    )
    hits: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    planner_durations: list[float] = []
    for observation in gold_observations:
        retrieved = observation.ranked_document_chunk_ids[:k]
        matching_ranks = tuple(
            rank
            for rank, document_chunk_id in enumerate(retrieved, start=1)
            if document_chunk_id in observation.gold_document_chunk_ids
        )
        hits.append(float(bool(matching_ranks)))
        recalls.append(len(matching_ranks) / len(observation.gold_document_chunk_ids))
        reciprocal_ranks.append(1 / matching_ranks[0] if matching_ranks else 0.0)
    for observation in observations:
        if observation.planner_latency_ms is not None:
            planner_durations.append(observation.planner_latency_ms)

    return BenchmarkMetrics(
        case_count=count,
        gold_case_count=len(gold_observations),
        hit_at_k=_mean(hits),
        recall_at_k=_mean(recalls),
        mrr=_mean(reciprocal_ranks),
        no_results_rate=_rate(
            sum(
                observation.decision is RetrievalDecision.NO_RESULTS for observation in observations
            ),
            count,
        ),
        wrong_scope_rate=_rate(sum(observation.wrong_scope for observation in observations), count),
        anchor_drift_rate=_rate(
            sum(observation.anchor_drift for observation in observations), count
        ),
        planner_latency_p50_ms=_nearest_rank_percentile(planner_durations, 0.50),
        planner_latency_p95_ms=_nearest_rank_percentile(planner_durations, 0.95),
        mean_end_to_end_latency_ms=_mean(
            [observation.end_to_end_latency_ms for observation in observations]
        ),
        fallback_rate=_rate(
            sum(observation.fallback_kind is not FallbackKind.NONE for observation in observations),
            count,
        ),
        expected_injected_fallback_rate=_rate(
            sum(
                observation.fallback_kind is FallbackKind.EXPECTED_INJECTED
                for observation in observations
            ),
            count,
        ),
        unexpected_runtime_fallback_rate=_rate(
            sum(
                observation.fallback_kind is FallbackKind.UNEXPECTED_RUNTIME
                for observation in observations
            ),
            count,
        ),
    )


def compare_benchmark_modes(
    raw_observations: tuple[BenchmarkObservation, ...],
    planned_observations: tuple[BenchmarkObservation, ...],
    *,
    k: int,
) -> BenchmarkComparison:
    """Compare matching raw and planned fixture IDs without inspecting any text."""

    _validate_mode(raw_observations, BenchmarkMode.RAW)
    _validate_mode(planned_observations, BenchmarkMode.PLANNED)
    raw_case_ids = {observation.case_id for observation in raw_observations}
    planned_case_ids = {observation.case_id for observation in planned_observations}
    if raw_case_ids != planned_case_ids:
        raise ValueError("raw and planned observations must have identical case IDs")
    raw = aggregate_benchmark_metrics(raw_observations, k=k)
    planned = aggregate_benchmark_metrics(planned_observations, k=k)
    return BenchmarkComparison(
        raw=raw,
        planned=planned,
        matched_case_count=len(raw_case_ids),
        end_to_end_latency_delta_ms=(
            planned.mean_end_to_end_latency_ms - raw.mean_end_to_end_latency_ms
        ),
    )


def _validate_k(k: int) -> None:
    if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= MAX_BENCHMARK_K:
        raise ValueError(f"k must be between 1 and {MAX_BENCHMARK_K}")


def _validate_unique_case_ids(observations: tuple[BenchmarkObservation, ...]) -> None:
    if not isinstance(observations, tuple):
        raise TypeError("observations must be a tuple")
    if len({observation.case_id for observation in observations}) != len(observations):
        raise ValueError("observations must have unique case IDs")


def _validate_mode(observations: tuple[BenchmarkObservation, ...], mode: BenchmarkMode) -> None:
    _validate_unique_case_ids(observations)
    if any(observation.mode is not mode for observation in observations):
        raise ValueError(f"observations must all use {mode.value} mode")


def _validate_duration(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite nonnegative duration")


def _validate_rate(value: float) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("metric rates must be finite values between 0 and 1")


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: list[float]) -> float:
    return fsum(values) / len(values) if values else 0.0


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[ceil(percentile * len(ordered)) - 1]
