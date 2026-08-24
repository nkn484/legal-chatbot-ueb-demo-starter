"""Read-only, content-free Phase-B1 semantic latency runtime probe.

This diagnostic deliberately does not represent the current production retrieval
latency.  It measures an exact semantic candidate path alongside the existing
diagnostic reader and retains only bounded timing, count, and plan-shape data.
Questions, vectors, SQL, plans, evidence, and identifiers remain local.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from math import isfinite
from numbers import Real
from time import perf_counter
from typing import Any

from sqlalchemy import select, text

from legal_chatbot.diagnostics.phase_b1_retrieval_engine import (
    PlanSummary,
    percentile,
    safe_plan_summary,
)
from legal_chatbot.documents.orm import ChunkEmbedding
from legal_chatbot.documents.quality_candidate_reader import PostgresQualityCandidateReader
from legal_chatbot.retrieval.quality_repair.models import RetrievalLane
from legal_chatbot.retrieval.quality_repair.ranking import (
    build_lane_document_pool,
    fused_diagnostic_top50,
    merge_chunk_candidates,
)
from legal_chatbot.semantic.constants import SEMANTIC_DIMENSION
from legal_chatbot.semantic.models import SemanticEmbeddingBatch

PHASE4_EXACT_SEMANTIC_CANDIDATE_PATH = "PHASE4_EXACT_SEMANTIC_CANDIDATE_PATH"
DIAGNOSTIC_EXACT_PATH = "DIAGNOSTIC_EXACT_PATH"
DIAGNOSTIC_WITH_EXPLAIN_PATH = "DIAGNOSTIC_WITH_EXPLAIN_PATH"
ACTIVE_SOURCE_IDS = ("VBQPPL", "VNU", "UEB")

_WARMUP_TEXT = "semantic retrieval warmup"
_HNSW_INDEX_NAME = "ix_chunk_embeddings_embedding_hnsw_cosine"


@dataclass(frozen=True)
class LatencyProbeCase:
    """A probe input whose question is never shown by its representation."""

    case_id: str
    question: str = field(repr=False)
    expected_numbers: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class StageNotImplemented:
    elapsed_ms: float = 0.0
    status: str = "NOT_IMPLEMENTED"


@dataclass(frozen=True)
class Phase4ExactSemanticMetrics:
    path: str
    transaction_setup_ms: float
    sql_ms: float
    collapse_ms: float
    transaction_ms: float
    total_ms: float
    data_query_count: int = 1
    result_document_version_count: int = 0


@dataclass(frozen=True)
class DiagnosticExactMetrics:
    path: str
    semantic_ms: float
    content_ms: float
    title_ms: float
    collapse_ms: float
    fusion_ms: float
    transaction_ms: float
    transaction_other_ms: float
    total_ms: float
    data_query_count: int
    explain_query_count: int
    query_count: int
    lane_natural_expected: dict[str, bool] = field(default_factory=dict)
    lane_collapsed_expected: dict[str, bool] = field(default_factory=dict)
    fused_expected: bool = False


@dataclass(frozen=True)
class DiagnosticExplainMetrics:
    path: str
    wall_ms: float
    transaction_ms: float
    explain_overhead_ms: float
    data_query_count: int
    explain_query_count: int
    query_count: int


@dataclass(frozen=True)
class PlanProbeSummary:
    """Allowlisted plan facts; neither SQL nor PostgreSQL's plan JSON is retained."""

    label: str
    requested_limit: int
    plan: PlanSummary
    cosine_operator_known: bool
    limit_evidence: bool
    hnsw_index_used: bool
    hnsw_index_available: bool

    def to_public_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "requested_limit": self.requested_limit,
            "cosine_operator_known": self.cosine_operator_known,
            "limit_evidence": self.limit_evidence,
            "hnsw_index_used": self.hnsw_index_used,
            "hnsw_index_available": self.hnsw_index_available,
            "plan_summary": self.plan.safe(),
        }


@dataclass(frozen=True)
class LatencyProbeCaseResult:
    """Safe per-case timing data only; this type contains no question or evidence."""

    case_id: str
    embedding_ms: float
    phase4: Phase4ExactSemanticMetrics
    diagnostic: DiagnosticExactMetrics
    diagnostic_with_explain: DiagnosticExplainMetrics
    analyzer: StageNotImplemented
    hydration: StageNotImplemented
    plans: tuple[PlanProbeSummary, ...]
    plan_query_count: int

    def to_public_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "embedding_ms": self.embedding_ms,
            "phase4": asdict(self.phase4),
            "diagnostic": asdict(self.diagnostic),
            "diagnostic_with_explain": asdict(self.diagnostic_with_explain),
            "analyzer": asdict(self.analyzer),
            "hydration": asdict(self.hydration),
            "plans": [plan.to_public_dict() for plan in self.plans],
            "plan_query_count": self.plan_query_count,
        }


@dataclass(frozen=True)
class LatencyProbeCounts:
    embedding_call_count: int
    timed_embedding_call_count: int
    database_warmup_call_count: int
    database_warmup_data_query_count: int
    database_warmup_explain_query_count: int
    phase4_exact_path_count: int
    diagnostic_no_explain_reader_call_count: int
    diagnostic_with_explain_reader_call_count: int
    plan_query_count: int
    hnsw_capability_query_count: int
    data_query_count: int
    explain_query_count: int
    duplicate_query_count: int


@dataclass(frozen=True)
class LatencyProbeResult:
    """Safe standalone probe result, including separate model-warmup timing."""

    warmup_ms: float
    cases: tuple[LatencyProbeCaseResult, ...]
    aggregates: dict[str, dict[str, float]]
    counts: LatencyProbeCounts
    # This is intentionally retained only for the in-process Q6 diagnostic.  It
    # is excluded from repr and every public report serialization.
    vectors_by_case: dict[str, tuple[float, ...]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        expected_case_ids = {case.case_id for case in self.cases}
        if set(self.vectors_by_case) != expected_case_ids:
            raise ValueError("vectors_by_case must contain exactly one vector per case")
        checked: dict[str, tuple[float, ...]] = {}
        for case_id, vector in self.vectors_by_case.items():
            if not isinstance(case_id, str) or not case_id:
                raise ValueError("vectors_by_case keys must be nonblank case IDs")
            if len(vector) != SEMANTIC_DIMENSION:
                raise ValueError("vectors_by_case vectors must be 384-dimensional")
            if any(
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not isfinite(float(value))
                for value in vector
            ):
                raise ValueError("vectors_by_case vectors must contain finite numeric values")
            checked[case_id] = tuple(float(value) for value in vector)
        object.__setattr__(self, "vectors_by_case", checked)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "warmup_ms": self.warmup_ms,
            "cases": [case.to_public_dict() for case in self.cases],
            "aggregates": self.aggregates,
            "counts": asdict(self.counts),
        }


def _milliseconds(started: float) -> float:
    return round((perf_counter() - started) * 1_000, 3)


async def _embed_vector(embedder: Any, private_text: str) -> tuple[float, ...]:
    batch = await embedder.embed_query(private_text)
    if not isinstance(batch, SemanticEmbeddingBatch) or len(batch.vectors) != 1:
        raise ValueError("E5 embedder must return one semantic embedding vector")
    vector = tuple(batch.vectors[0])
    if len(vector) != SEMANTIC_DIMENSION:
        raise ValueError("E5 embedder must return one 384-dimensional vector")
    return vector


def _lane_elapsed_ms(read: Any, lane: RetrievalLane) -> float:
    for metric in read.lane_metrics:
        if metric.lane is lane:
            return float(metric.sql_elapsed_ms)
    return 0.0


async def _phase4_exact_semantic(
    session_factory: Any, reader: PostgresQualityCandidateReader, vector: tuple[float, ...]
) -> Phase4ExactSemanticMetrics:
    """Measure the bounded exact semantic candidate path, not a runtime default path."""

    total_started = perf_counter()
    transaction_started = perf_counter()
    async with session_factory() as session:
        async with session.begin():
            # The isolation statement must remain first in this transaction.
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            await session.execute(text("SET LOCAL enable_indexscan = off"))
            await session.execute(text("SET LOCAL enable_bitmapscan = off"))
            statement = reader._semantic_statement(ACTIVE_SOURCE_IDS, vector, 8)  # noqa: SLF001
            sql_started = perf_counter()
            rows = list((await session.execute(statement)).all())
            sql_ms = _milliseconds(sql_started)
    transaction_ms = _milliseconds(transaction_started)
    collapse_started = perf_counter()
    candidates = reader._candidates(  # noqa: SLF001
        rows, RetrievalLane.SEMANTIC, 1, sql_ms, len(rows)
    )
    collapsed = build_lane_document_pool(candidates, RetrievalLane.SEMANTIC, 8)
    collapse_ms = _milliseconds(collapse_started)
    return Phase4ExactSemanticMetrics(
        path=PHASE4_EXACT_SEMANTIC_CANDIDATE_PATH,
        transaction_setup_ms=round((sql_started - transaction_started) * 1_000, 3),
        sql_ms=sql_ms,
        collapse_ms=collapse_ms,
        transaction_ms=transaction_ms,
        total_ms=_milliseconds(total_started),
        result_document_version_count=len(collapsed.candidates),
    )


async def _diagnostic_exact(
    reader: PostgresQualityCandidateReader,
    question: str,
    vector: tuple[float, ...],
    expected_numbers: tuple[str, ...] = (),
) -> DiagnosticExactMetrics:
    total_started = perf_counter()
    read = await reader.read_candidates(question, ACTIVE_SOURCE_IDS, vector, 50, explain=False)
    collapse_started = perf_counter()
    merged = merge_chunk_candidates(
        candidate for candidates in read.lane_candidates.values() for candidate in candidates
    )
    lane_pools = tuple(
        build_lane_document_pool(merged.candidates, lane, 50) for lane in RetrievalLane
    )
    collapse_ms = _milliseconds(collapse_started)
    fusion_started = perf_counter()
    fused = fused_diagnostic_top50(lane_pools)
    fusion_ms = _milliseconds(fusion_started)
    lane_data_ms = sum(_lane_elapsed_ms(read, lane) for lane in RetrievalLane)
    expected = frozenset(expected_numbers)

    def hits(candidates: Any) -> bool:
        return bool(
            expected
            and any(
                candidate.identity.document_number_normalized in expected
                for candidate in candidates
            )
        )
    return DiagnosticExactMetrics(
        path=DIAGNOSTIC_EXACT_PATH,
        semantic_ms=_lane_elapsed_ms(read, RetrievalLane.SEMANTIC),
        content_ms=_lane_elapsed_ms(read, RetrievalLane.CONTENT_FTS),
        title_ms=_lane_elapsed_ms(read, RetrievalLane.TITLE_FTS),
        collapse_ms=collapse_ms,
        fusion_ms=fusion_ms,
        transaction_ms=round(float(read.transaction_elapsed_ms), 3),
        transaction_other_ms=round(max(float(read.transaction_elapsed_ms) - lane_data_ms, 0.0), 3),
        total_ms=_milliseconds(total_started),
        data_query_count=read.data_query_count,
        explain_query_count=read.explain_query_count,
        query_count=read.query_count,
        lane_natural_expected={
            lane.value: hits(read.lane_candidates.get(lane, ())) for lane in RetrievalLane
        },
        lane_collapsed_expected={lane.lane.value: hits(lane.candidates) for lane in lane_pools},
        fused_expected=hits(fused.candidates),
    )


async def _diagnostic_with_explain(
    reader: PostgresQualityCandidateReader, question: str, vector: tuple[float, ...]
) -> DiagnosticExplainMetrics:
    wall_started = perf_counter()
    read = await reader.read_candidates(question, ACTIVE_SOURCE_IDS, vector, 50, explain=True)
    lane_data_ms = sum(_lane_elapsed_ms(read, lane) for lane in RetrievalLane)
    return DiagnosticExplainMetrics(
        path=DIAGNOSTIC_WITH_EXPLAIN_PATH,
        wall_ms=_milliseconds(wall_started),
        transaction_ms=round(float(read.transaction_elapsed_ms), 3),
        explain_overhead_ms=round(max(float(read.transaction_elapsed_ms) - lane_data_ms, 0.0), 3),
        data_query_count=read.data_query_count,
        explain_query_count=read.explain_query_count,
        query_count=read.query_count,
    )


async def _plan_payload(session: Any, statement: Any) -> object:
    """Execute a private parameterized EXPLAIN and return its ephemeral payload."""

    dialect = session.bind.dialect if session.bind is not None else None
    if dialect is None:
        raise RuntimeError("PostgreSQL session is not bound")
    compiled = statement.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
    params = dict(compiled.params)
    values = []
    for name in compiled.positiontup or ():
        value = params[name]
        processor = compiled._bind_processors.get(name)
        values.append(processor(value) if processor is not None else value)
    connection = await session.connection()
    result = await connection.exec_driver_sql(
        f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}", tuple(values)
    )
    return result.scalar_one()


async def _semantic_plan(
    session_factory: Any,
    reader: PostgresQualityCandidateReader,
    vector: tuple[float, ...],
    *,
    label: str,
    limit: int,
    exact_scans_disabled: bool,
    hnsw_index_available: bool,
) -> PlanProbeSummary:
    """Run one read-only plan probe and discard all raw planning/execution data."""

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            setting = "off" if exact_scans_disabled else "on"
            await session.execute(text(f"SET LOCAL enable_indexscan = {setting}"))
            await session.execute(text(f"SET LOCAL enable_bitmapscan = {setting}"))
            if exact_scans_disabled:
                statement = reader._semantic_statement(  # noqa: SLF001
                    ACTIVE_SOURCE_IDS, vector, limit
                )
            else:
                # Isolate pgvector capability from the production-equivalent
                # joins/filters. This is a diagnostic control, not a candidate path.
                statement = (
                    select(ChunkEmbedding.id)
                    .order_by(ChunkEmbedding.embedding.cosine_distance(list(vector)))
                    .limit(limit)
                )
            payload = await _plan_payload(session, statement)
    summary = safe_plan_summary(payload)
    return PlanProbeSummary(
        label=label,
        requested_limit=limit,
        plan=summary,
        # `_semantic_statement` is the approved cosine-distance statement builder.
        cosine_operator_known=True,
        limit_evidence=summary.limit_above_scan,
        hnsw_index_used=_HNSW_INDEX_NAME in summary.index_names,
        hnsw_index_available=hnsw_index_available,
    )


async def _hnsw_index_available(session_factory: Any) -> bool:
    """Return only whether the known ANN index is present, never its catalog output."""

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            result = await session.execute(
                text("SELECT to_regclass(:index_name) IS NOT NULL"),
                {"index_name": _HNSW_INDEX_NAME},
            )
            return bool(result.scalar_one())


def _aggregates(cases: Iterable[LatencyProbeCaseResult]) -> dict[str, dict[str, float]]:
    """Aggregate every timed per-case stage with the existing nearest-rank helper."""

    rows = tuple(cases)
    stages = {
        "embedding_ms": (case.embedding_ms for case in rows),
        "phase4_transaction_setup_ms": (case.phase4.transaction_setup_ms for case in rows),
        "phase4_sql_ms": (case.phase4.sql_ms for case in rows),
        "phase4_collapse_ms": (case.phase4.collapse_ms for case in rows),
        "phase4_transaction_ms": (case.phase4.transaction_ms for case in rows),
        "phase4_total_ms": (case.phase4.total_ms for case in rows),
        "diagnostic_semantic_ms": (case.diagnostic.semantic_ms for case in rows),
        "diagnostic_content_ms": (case.diagnostic.content_ms for case in rows),
        "diagnostic_title_ms": (case.diagnostic.title_ms for case in rows),
        "diagnostic_collapse_ms": (case.diagnostic.collapse_ms for case in rows),
        "diagnostic_fusion_ms": (case.diagnostic.fusion_ms for case in rows),
        "diagnostic_transaction_ms": (case.diagnostic.transaction_ms for case in rows),
        "diagnostic_transaction_other_ms": (
            case.diagnostic.transaction_other_ms for case in rows
        ),
        "diagnostic_total_ms": (case.diagnostic.total_ms for case in rows),
        "explain_wall_ms": (case.diagnostic_with_explain.wall_ms for case in rows),
        "explain_transaction_ms": (
            case.diagnostic_with_explain.transaction_ms for case in rows
        ),
        "explain_overhead_ms": (
            case.diagnostic_with_explain.explain_overhead_ms for case in rows
        ),
        "analyzer_ms": (case.analyzer.elapsed_ms for case in rows),
        "hydration_ms": (case.hydration.elapsed_ms for case in rows),
    }
    aggregates: dict[str, dict[str, float]] = {}
    for name, values in stages.items():
        measured = tuple(values)
        aggregates[name] = {
            "p50_ms": percentile(measured, 50),
            "p95_ms": percentile(measured, 95),
        }
    return aggregates


async def probe_latency_cases(
    session_factory: Any,
    reader: PostgresQualityCandidateReader,
    embedder: Any,
    cases: Iterable[LatencyProbeCase],
    *,
    explain: bool = True,
) -> LatencyProbeResult:
    """Run one warmed E5 embedding and bounded read-only probes per input case.

    ``explain=False`` keeps the explain-reader call out of the timing run, but
    plan probes still run so the exact/ANN control plan evidence remains present.
    The default follows the complete Phase-B1 probe contract.
    """

    if not isinstance(explain, bool):
        raise ValueError("explain must be a boolean")
    normalized_cases = tuple(cases)
    if len({case.case_id for case in normalized_cases}) != len(normalized_cases):
        raise ValueError("case IDs must be unique")

    warmup_started = perf_counter()
    warmup_vector = await _embed_vector(embedder, _WARMUP_TEXT)
    warmup_ms = _milliseconds(warmup_started)
    hnsw_index_available = await _hnsw_index_available(session_factory)
    warmup_phase4 = await _phase4_exact_semantic(session_factory, reader, warmup_vector)
    warmup_diagnostic = await _diagnostic_exact(reader, _WARMUP_TEXT, warmup_vector)
    warmup_with_explain = (
        await _diagnostic_with_explain(reader, _WARMUP_TEXT, warmup_vector)
        if explain
        else DiagnosticExplainMetrics(
            path=DIAGNOSTIC_WITH_EXPLAIN_PATH,
            wall_ms=0.0,
            transaction_ms=0.0,
            explain_overhead_ms=0.0,
            data_query_count=0,
            explain_query_count=0,
            query_count=0,
        )
    )

    results: list[LatencyProbeCaseResult] = []
    vectors_by_case: dict[str, tuple[float, ...]] = {}
    diagnostic_with_explain_calls = 0
    for case in normalized_cases:
        embedding_started = perf_counter()
        vector = await _embed_vector(embedder, case.question)
        vectors_by_case[case.case_id] = vector
        embedding_ms = _milliseconds(embedding_started)
        phase4 = await _phase4_exact_semantic(session_factory, reader, vector)
        diagnostic = await _diagnostic_exact(reader, case.question, vector, case.expected_numbers)
        if explain:
            diagnostic_with_explain = await _diagnostic_with_explain(reader, case.question, vector)
            diagnostic_with_explain_calls += 1
        else:
            diagnostic_with_explain = DiagnosticExplainMetrics(
                path=DIAGNOSTIC_WITH_EXPLAIN_PATH,
                wall_ms=0.0,
                transaction_ms=0.0,
                explain_overhead_ms=0.0,
                data_query_count=0,
                explain_query_count=0,
                query_count=0,
            )
        plans = (
            await _semantic_plan(
                session_factory,
                reader,
                vector,
                label="EXACT_SEMANTIC_TOP8_SCANS_DISABLED",
                limit=8,
                exact_scans_disabled=True,
                hnsw_index_available=hnsw_index_available,
            ),
            await _semantic_plan(
                session_factory,
                reader,
                vector,
                label="EXACT_SEMANTIC_TOP50_SCANS_DISABLED",
                limit=50,
                exact_scans_disabled=True,
                hnsw_index_available=hnsw_index_available,
            ),
            await _semantic_plan(
                session_factory,
                reader,
                vector,
                label="ANN_CONTROL_SEMANTIC_TOP50_SCANS_ENABLED",
                limit=50,
                exact_scans_disabled=False,
                hnsw_index_available=hnsw_index_available,
            ),
        )
        results.append(
            LatencyProbeCaseResult(
                case_id=case.case_id,
                embedding_ms=embedding_ms,
                phase4=phase4,
                diagnostic=diagnostic,
                diagnostic_with_explain=diagnostic_with_explain,
                analyzer=StageNotImplemented(),
                hydration=StageNotImplemented(),
                plans=plans,
                plan_query_count=len(plans),
            )
        )
    return LatencyProbeResult(
        warmup_ms=warmup_ms,
        cases=tuple(results),
        aggregates=_aggregates(results),
        counts=LatencyProbeCounts(
            embedding_call_count=len(results) + 1,
            timed_embedding_call_count=len(results),
            database_warmup_call_count=3 if explain else 2,
            database_warmup_data_query_count=(
                warmup_phase4.data_query_count
                + warmup_diagnostic.data_query_count
                + warmup_with_explain.data_query_count
            ),
            database_warmup_explain_query_count=(
                warmup_diagnostic.explain_query_count
                + warmup_with_explain.explain_query_count
            ),
            phase4_exact_path_count=len(results),
            diagnostic_no_explain_reader_call_count=len(results),
            diagnostic_with_explain_reader_call_count=diagnostic_with_explain_calls,
            plan_query_count=len(results) * 3,
            hnsw_capability_query_count=1,
            data_query_count=sum(
                case.phase4.data_query_count
                + case.diagnostic.data_query_count
                + case.diagnostic_with_explain.data_query_count
                for case in results
            ),
            explain_query_count=sum(
                case.diagnostic.explain_query_count
                + case.diagnostic_with_explain.explain_query_count
                for case in results
            )
            + len(results) * 3,
            # The explain reader executes its candidate data queries again before
            # its EXPLAINs.  Count those repeated data queries, not model calls.
            duplicate_query_count=sum(
                case.diagnostic_with_explain.data_query_count for case in results
            ),
        ),
        vectors_by_case=vectors_by_case,
    )
