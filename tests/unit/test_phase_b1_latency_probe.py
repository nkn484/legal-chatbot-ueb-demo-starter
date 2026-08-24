"""Fake-only tests for the standalone, content-free Phase-B1 latency probe."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pytest

from legal_chatbot.diagnostics import phase_b1_latency_probe as probe
from legal_chatbot.diagnostics.phase_b1_retrieval_engine import PlanSummary
from legal_chatbot.semantic.models import SemanticEmbeddingBatch


class _Embedder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed_query(self, question: str) -> SemanticEmbeddingBatch:
        self.calls.append(question)
        return SemanticEmbeddingBatch(vectors=(tuple([1.0] + [0.0] * 383),))


def _plan(label: str, limit: int, available: bool) -> probe.PlanProbeSummary:
    return probe.PlanProbeSummary(
        label=label,
        requested_limit=limit,
        plan=PlanSummary(
            root_node_type="Limit",
            node_types=("Limit", "Seq Scan"),
            scan_types=("Seq Scan",),
            index_names=(),
            actual_rows=1,
            planning_ms=0.1,
            execution_ms=0.2,
            shared_hit=1,
            shared_read=0,
            temp_read=0,
            temp_written=0,
            limit_above_scan=True,
        ),
        cosine_operator_known=True,
        limit_evidence=True,
        hnsw_index_used=False,
        hnsw_index_available=available,
    )


@pytest.mark.asyncio
async def test_probe_warms_once_reuses_one_timed_vector_and_keeps_question_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timed_vector_ids: list[int] = []

    async def phase4(_sessions: Any, _reader: Any, vector: tuple[float, ...]):
        timed_vector_ids.append(id(vector))
        return probe.Phase4ExactSemanticMetrics(
            probe.PHASE4_EXACT_SEMANTIC_CANDIDATE_PATH, 1, 2, 3, 4, 5, 1, 1
        )

    async def diagnostic(
        _reader: Any,
        _question: str,
        vector: tuple[float, ...],
        _expected_numbers: tuple[str, ...] = (),
    ):
        timed_vector_ids.append(id(vector))
        return probe.DiagnosticExactMetrics(
            probe.DIAGNOSTIC_EXACT_PATH, 1, 2, 3, 4, 5, 6, 0, 7, 4, 0, 4
        )

    async def diagnostic_explain(_reader: Any, _question: str, vector: tuple[float, ...]):
        timed_vector_ids.append(id(vector))
        return probe.DiagnosticExplainMetrics(
            probe.DIAGNOSTIC_WITH_EXPLAIN_PATH, 8, 7, 1, 4, 4, 8
        )

    async def plan(
        _sessions: Any,
        _reader: Any,
        vector: tuple[float, ...],
        *,
        label: str,
        limit: int,
        exact_scans_disabled: bool,
        hnsw_index_available: bool,
    ) -> probe.PlanProbeSummary:
        del exact_scans_disabled
        timed_vector_ids.append(id(vector))
        return _plan(label, limit, hnsw_index_available)

    async def hnsw_available(_sessions: Any) -> bool:
        return True

    monkeypatch.setattr(probe, "_phase4_exact_semantic", phase4)
    monkeypatch.setattr(probe, "_diagnostic_exact", diagnostic)
    monkeypatch.setattr(probe, "_diagnostic_with_explain", diagnostic_explain)
    monkeypatch.setattr(probe, "_semantic_plan", plan)
    monkeypatch.setattr(probe, "_hnsw_index_available", hnsw_available)
    embedder = _Embedder()

    result = await probe.probe_latency_cases(
        cast(Any, object()),
        cast(Any, object()),
        embedder,
        (probe.LatencyProbeCase("case-1", "private question must not escape"),),
    )

    assert len(embedder.calls) == 2  # one warmup and exactly one timed embed
    vector_use_counts = sorted(
        timed_vector_ids.count(vector_id) for vector_id in set(timed_vector_ids)
    )
    assert vector_use_counts == [3, 6]
    assert result.counts.embedding_call_count == 2
    assert result.counts.timed_embedding_call_count == 1
    assert result.counts.database_warmup_call_count == 3
    assert result.counts.database_warmup_data_query_count == 9
    assert result.counts.database_warmup_explain_query_count == 4
    assert result.counts.data_query_count == 9
    assert result.counts.explain_query_count == 7
    assert result.counts.duplicate_query_count == 4
    assert result.counts.hnsw_capability_query_count == 1
    assert result.vectors_by_case["case-1"] == tuple([1.0] + [0.0] * 383)
    assert "vectors_by_case" not in repr(result)
    assert result.aggregates["phase4_transaction_setup_ms"]["p50_ms"] == 1
    assert result.aggregates["phase4_transaction_setup_ms"]["p95_ms"] == 1
    assert result.aggregates["diagnostic_transaction_ms"]["p50_ms"] == 6
    assert result.aggregates["diagnostic_transaction_ms"]["p95_ms"] == 6
    report = cast(dict[str, Any], result.to_public_dict())
    assert "private question must not escape" not in str(report)
    assert "vectors_by_case" not in report
    assert report["cases"][0]["plans"][0]["requested_limit"] == 8
    assert report["cases"][0]["plans"][0]["limit_evidence"] is True
    assert report["cases"][0]["plans"][0]["hnsw_index_available"] is True


@pytest.mark.asyncio
async def test_probe_can_skip_reader_explain_but_keeps_safe_plan_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def phase4(_sessions: Any, _reader: Any, _vector: tuple[float, ...]):
        return probe.Phase4ExactSemanticMetrics("phase4", 0, 0, 0, 0, 0)

    async def diagnostic(
        _reader: Any,
        _question: str,
        _vector: tuple[float, ...],
        _expected_numbers: tuple[str, ...] = (),
    ):
        return probe.DiagnosticExactMetrics("diagnostic", 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 3)

    async def plan(
        _sessions: Any,
        _reader: Any,
        _vector: tuple[float, ...],
        *,
        label: str,
        limit: int,
        exact_scans_disabled: bool,
        hnsw_index_available: bool,
    ) -> probe.PlanProbeSummary:
        del exact_scans_disabled
        return _plan(label, limit, hnsw_index_available)

    async def hnsw_available(_sessions: Any) -> bool:
        return False

    monkeypatch.setattr(probe, "_phase4_exact_semantic", phase4)
    monkeypatch.setattr(probe, "_diagnostic_exact", diagnostic)
    monkeypatch.setattr(probe, "_semantic_plan", plan)
    monkeypatch.setattr(probe, "_hnsw_index_available", hnsw_available)

    result = await probe.probe_latency_cases(
        object(),
        cast(Any, object()),
        _Embedder(),
        (probe.LatencyProbeCase("case-1", "private"),),
        explain=False,
    )

    assert result.counts.diagnostic_with_explain_reader_call_count == 0
    assert result.counts.plan_query_count == 3
    assert result.cases[0].diagnostic_with_explain.query_count == 0
    assert all(not item.hnsw_index_available for item in result.cases[0].plans)
    assert result.counts.duplicate_query_count == 0


class _EmptyResult:
    def all(self) -> list[Any]:
        return []


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, _type: object, _value: object, _traceback: object) -> None:
        return None


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, _type: object, _value: object, _traceback: object) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction()

    async def execute(self, _statement: object) -> _EmptyResult:
        return _EmptyResult()


class _SessionFactory:
    def __call__(self) -> _Session:
        return _Session()


class _Phase4Reader:
    @staticmethod
    def _semantic_statement(_sources: object, _vector: object, _limit: int) -> object:
        return object()

    @staticmethod
    def _candidates(
        _rows: object, _lane: object, _count: int, _elapsed: float, _size: int
    ) -> tuple[()]:
        return ()


@pytest.mark.asyncio
async def test_phase4_timing_fields_and_setup_are_milliseconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((1.0, 1.1, 1.6, 1.8, 2.0, 2.1, 2.2, 2.3))
    monkeypatch.setattr(probe, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(
        probe,
        "build_lane_document_pool",
        lambda _candidates, _lane, _limit: type("Pool", (), {"candidates": ()})(),
    )

    result = await probe._phase4_exact_semantic(
        _SessionFactory(),  # type: ignore[arg-type]
        _Phase4Reader(),  # type: ignore[arg-type]
        (1.0,),
    )

    assert result.transaction_setup_ms == 500.0
    assert result.sql_ms == 200.0
    assert result.transaction_ms == 900.0
    assert result.collapse_ms == 100.0
    assert result.total_ms == 1300.0


def test_private_vectors_require_one_finite_384d_vector_per_case() -> None:
    case = probe.LatencyProbeCaseResult(
        case_id="case-1",
        embedding_ms=0,
        phase4=probe.Phase4ExactSemanticMetrics("phase4", 0, 0, 0, 0, 0),
        diagnostic=probe.DiagnosticExactMetrics("diagnostic", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        diagnostic_with_explain=probe.DiagnosticExplainMetrics("explain", 0, 0, 0, 0, 0, 0),
        analyzer=probe.StageNotImplemented(),
        hydration=probe.StageNotImplemented(),
        plans=(),
        plan_query_count=0,
    )
    counts = probe.LatencyProbeCounts(
        embedding_call_count=0,
        timed_embedding_call_count=0,
        database_warmup_call_count=0,
        database_warmup_data_query_count=0,
        database_warmup_explain_query_count=0,
        phase4_exact_path_count=0,
        diagnostic_no_explain_reader_call_count=0,
        diagnostic_with_explain_reader_call_count=0,
        plan_query_count=0,
        hnsw_capability_query_count=0,
        data_query_count=0,
        explain_query_count=0,
        duplicate_query_count=0,
    )
    valid = probe.LatencyProbeResult(
        warmup_ms=0,
        cases=(case,),
        aggregates={},
        counts=counts,
        vectors_by_case={"case-1": tuple([1.0] + [0.0] * 383)},
    )

    with pytest.raises(ValueError, match="finite"):
        replace(valid, vectors_by_case={"case-1": tuple([float("nan")] * 384)})
    with pytest.raises(ValueError, match="exactly one vector"):
        replace(valid, vectors_by_case={})
