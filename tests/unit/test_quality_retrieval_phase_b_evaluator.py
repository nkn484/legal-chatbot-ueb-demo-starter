"""Focused no-DB checks for the Phase B evaluator contract."""

import json
from pathlib import Path
from uuid import UUID, uuid5

import openpyxl
import pytest
from scripts.evaluate_quality_retrieval_phase_b import (
    DEFAULT_OUTPUT,
    EvaluationError,
    ParentCase,
    QueryResult,
    _state_invariants,
    build_parser,
    citation_score_mapping,
    evaluate_query,
    gate_b,
    parse_m2_set,
    resolve_output_paths,
    semantic_reference_summary,
    set_b_rows,
    set_c_rows,
    write_reports,
)

from legal_chatbot.documents.quality_candidate_reader import FTSQueryMode
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
    PoolMeasurementSummary,
    PoolReferenceSummary,
    build_lane_document_pool,
    select_pareto_pool,
    with_lane_unique_contributions,
)
from legal_chatbot.retrieval.quality_repair.trace import LaneMetrics
from legal_chatbot.semantic.models import SemanticEmbeddingBatch


def _uuid(value: str) -> UUID:
    return uuid5(UUID("12345678-1234-5678-1234-567812345678"), value)


def _candidate(name: str, lane: RetrievalLane, rank: int = 1) -> CandidateEvidence:
    identity = DocumentIdentity(
        document_id=_uuid("document-" + name),
        document_version_id=_uuid("version-" + name),
        source_id=SourceId.VBQPPL,
        external_id="private-external-" + name,
        document_number_normalized="100/TEST-" + name,
        title="private-title-" + name,
        version_number=1,
        provenance_record_id=_uuid("provenance-" + name),
        provenance_type=ProvenanceType.SOURCE_FETCH,
        latest_ingested=True,
    )
    return CandidateEvidence(
        chunk_id=_uuid("chunk-" + name),
        identity=identity,
        ordinal=0,
        observations=(
            LaneObservation(
                lane=lane, rank=rank, score=0.5, query_count=1, elapsed_ms=1, rows_returned=1
            ),
        ),
        supporting_semantic_score=0.5 if lane is not RetrievalLane.CONTENT_FTS else None,
        source_scope=SourceScopeObservation.NONE,
        eligible=True,
    )


class _Embedder:
    calls = 0

    async def embed_query(self, _question: str) -> SemanticEmbeddingBatch:
        self.calls += 1
        return SemanticEmbeddingBatch(vectors=((1.0,) + (0.0,) * 383,))


class _Reader:
    calls = 0
    modes: list[FTSQueryMode]

    def __init__(self) -> None:
        self.modes = []

    async def read_candidates(
        self, _question, _sources, _vector, _limit, *, explain, fts_query_mode
    ):
        self.calls += 1
        self.modes.append(fts_query_mode)
        assert explain is True
        from legal_chatbot.documents.quality_candidate_reader import QualityCandidateReadResult

        bounded = fts_query_mode is FTSQueryMode.BOUNDED_OR
        return QualityCandidateReadResult(
            lane_candidates={lane: (_candidate(lane.value, lane),) for lane in RetrievalLane},
            lane_metrics=tuple(
                LaneMetrics(
                    lane=lane,
                    query_count=1,
                    elapsed_ms=5,
                    sql_elapsed_ms=5,
                    rows_returned=1,
                )
                for lane in RetrievalLane
            ),
            data_query_count=5 if bounded else 4,
            explain_query_count=4,
            query_count=9 if bounded else 8,
            transaction_elapsed_ms=1,
            requested_fts_query_mode=fts_query_mode,
            applied_fts_query_mode=fts_query_mode,
            fts_preparation_query_count=int(bounded),
            fts_preparation_elapsed_ms=2.0 if bounded else 0.0,
            bounded_or_selected_lexeme_count=2 if bounded else 0,
            bounded_or_source_lexeme_count=2 if bounded else 0,
        )


@pytest.mark.asyncio
async def test_ranking_pipeline_embeds_and_reads_once_then_builds_all_pools() -> None:
    embedder, reader = _Embedder(), _Reader()
    result = await evaluate_query(
        ParentCase("Q01", "private question", ("100/TEST",)),
        reader=reader,
        embedder=embedder,
        explain=True,
    )
    assert embedder.calls == reader.calls == 1
    assert reader.modes == [FTSQueryMode.NATURAL]
    assert result.data_query_count == 4
    assert result.explain_query_count == 4
    assert result.retrieval_eval_ms >= 15
    assert tuple(result.pools) == (8, 12, 16, 20)
    assert all(len(final) <= 3 for final in result.finals.values())


@pytest.mark.asyncio
async def test_evaluator_threads_bounded_or_once_and_adds_preparation_to_retrieval_latency(
) -> None:
    reader = _Reader()
    result = await evaluate_query(
        ParentCase("Q01", "private question", ("100/TEST",)),
        reader=reader,
        embedder=_Embedder(),
        explain=True,
        fts_query_mode=FTSQueryMode.BOUNDED_OR,
    )

    assert reader.calls == 1 and reader.modes == [FTSQueryMode.BOUNDED_OR]
    assert result.data_query_count == 5
    assert result.fts_preparation_elapsed_ms == 2.0
    assert result.retrieval_eval_ms >= 17


def test_cli_keeps_natural_defaults_and_resolves_mode_specific_output_stems(tmp_path: Path) -> None:
    parser = build_parser()
    natural = parser.parse_args([])
    resolve_output_paths(natural)
    assert natural.fts_query_mode is FTSQueryMode.NATURAL
    assert natural.output == DEFAULT_OUTPUT
    assert natural.json_output == DEFAULT_OUTPUT.with_suffix(".json")

    bounded = parser.parse_args(
        ["--fts-query-mode", "BOUNDED_OR", "--output-stem", str(tmp_path / "phase-b2a-bounded-or")]
    )
    resolve_output_paths(bounded)
    assert bounded.output == tmp_path / "phase-b2a-bounded-or.xlsx"
    assert bounded.json_output == tmp_path / "phase-b2a-bounded-or.json"
    assert bounded.markdown_output == tmp_path / "phase-b2a-bounded-or.md"

    with pytest.raises(ValueError, match="mode-specific"):
        resolve_output_paths(parser.parse_args(["--fts-query-mode", "BOUNDED_OR"]))


@pytest.mark.asyncio
async def test_semantic_reference_uses_semantic_lane_not_wall_latency() -> None:
    result = await evaluate_query(
        ParentCase("Q01", "private question", ("100/TEST-SEMANTIC",)),
        reader=_Reader(),
        embedder=_Embedder(),
        explain=True,
    )
    reference = semantic_reference_summary(
        (ParentCase("Q01", "private question", ("100/TEST-SEMANTIC",)),),
        (result,),
        {"100/TEST-SEMANTIC": ("VBQPPL",)},
    )
    assert reference.candidate_identity_count == 1
    assert reference.query_count == 1
    assert reference.p95_latency_ms < result.retrieval_eval_ms


def test_score_mapping_keeps_title_score_out_of_persisted_scores() -> None:
    title = _candidate("title", RetrievalLane.TITLE_FTS)
    pool = with_lane_unique_contributions(
        (build_lane_document_pool((title,), RetrievalLane.TITLE_FTS, 8),), 8
    )
    lexical, semantic = citation_score_mapping(pool.candidates[0])
    assert lexical is None
    assert semantic == 0.5


def test_m2_parser_requires_b30_c24(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    path.write_text(
        json.dumps({"sets": {"B": {"cases": []}, "C": {"cases": []}}}), encoding="utf-8"
    )
    with pytest.raises(EvaluationError):
        parse_m2_set(path)


def test_set_b_jaccard_and_set_c_invariant_labels_only() -> None:
    candidate = _candidate("shared", RetrievalLane.SEMANTIC)
    pool = with_lane_unique_contributions(
        (build_lane_document_pool((candidate,), RetrievalLane.SEMANTIC, 8),), 8
    )
    result_a = QueryResult(
        "Q01",
        "A",
        "PARENT",
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
        1,
        {},
        (),
        None,
        {size: pool for size in (8, 12, 16, 20)},
        {size: pool.candidates for size in (8, 12, 16, 20)},
    )
    result_b = QueryResult(
        "B-Q01-01",
        "B",
        "PARAPHRASE",
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        0,
        1,
        {},
        (),
        None,
        {size: pool for size in (8, 12, 16, 20)},
        {size: pool.candidates for size in (8, 12, 16, 20)},
    )
    result_c = QueryResult(
        "C-01",
        "C",
        "NO_EVIDENCE",
        0,
        0,
        0,
        0,
        0,
        0,
        13,
        0,
        13,
        {},
        (),
        None,
        {size: pool for size in (8, 12, 16, 20)},
        {size: pool.candidates for size in (8, 12, 16, 20)},
    )
    assert set_b_rows((result_a, result_b))[0]["jaccard"] == 1.0
    assert "QUERY_COUNT" in set_c_rows((result_c,))[0]["invariant_failures"]


def test_pareto_gate_and_content_free_report_sheets(tmp_path: Path) -> None:
    reference = PoolReferenceSummary(
        candidate_identity_count=25,
        nonexpected_candidate_rate=0,
        p95_latency_ms=100,
        query_count=1,
        set_c_failure_count=0,
    )
    measurements = tuple(
        PoolMeasurementSummary(
            pool_size=size,
            candidate_identity_count=27 + index,
            nonexpected_candidate_rate=0,
            p95_latency_ms=100,
            query_count=1,
            set_c_failure_count=0,
        )
        for index, size in enumerate((8, 12, 16, 20))
    )
    selection = select_pareto_pool(reference, measurements)
    rows = (
        {"pool_size": 8, "unique_expected_contribution": {lane.value: 1 for lane in RetrievalLane}},
    )
    gate = gate_b(
        selection,
        measurements,
        rows,
        ({"resolvable": True, "cleanup": "COMPLETED", "global_counts_match": True},),
    )
    xlsx, report_json, markdown = (
        tmp_path / "report.xlsx",
        tmp_path / "report.json",
        tmp_path / "report.md",
    )
    counts = {
        "reviewed_effect_imports": 0,
        "reviewed_effect_families": 0,
        "reviewed_effect_assertions": 0,
        "reviewed_effect_events": 0,
        "retrieval_runs": 17,
        "citations": 16,
    }
    state = _state_invariants(
        counts,
        dict(counts),
        {
            "defaults": {"quality_strategy": "disabled"},
            "active": {"quality_strategy": "disabled"},
            "static_runtime": {
                "runtime_service_imports_reviewed_effects": False,
                "runtime_service_imports_quality_execution": False,
            },
            "quality_defaults_off": True,
            "quality_active_off": True,
            "reviewed_effects_off": True,
            "flags_off": True,
        },
    )
    write_reports(
        xlsx_path=xlsx,
        json_path=report_json,
        markdown_path=markdown,
        a_rows=(),
        b_rows=(),
        c_rows=(),
        measurements=measurements,
        selection=selection,
        gate=gate,
        citation_rows=(),
        semantic_reference=reference,
        state_invariants=state,
    )
    book = openpyxl.load_workbook(xlsx, read_only=True)
    assert book.sheetnames == [
        "Summary",
        "Set A",
        "Pool Matrix",
        "Lane Contributions",
        "Set B",
        "Set C",
        "Cost",
        "Citation Invariants",
    ]
    assert "private question" not in report_json.read_text(encoding="utf-8")
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["phase_b2a_state_invariants"]["counts_unchanged"] is True
    assert payload["phase_b2a_state_invariants"]["reviewed_effect_registry_zero"] is True
    book.close()
