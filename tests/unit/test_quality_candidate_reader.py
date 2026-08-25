from math import inf, nan
from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.documents.fts_query import build_or_tsquery
from legal_chatbot.documents.quality_candidate_reader import (
    FTSQueryMode,
    PostgresQualityCandidateReader,
    QualityCandidateReadResult,
)
from legal_chatbot.retrieval.quality_repair.models import (
    CandidateEvidence,
    DocumentIdentity,
    LaneObservation,
    ProvenanceType,
    RetrievalLane,
    SourceId,
    SourceScopeObservation,
)
from legal_chatbot.retrieval.quality_repair.trace import LaneMetrics


def _vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "sources", "vector", "limit"),
    [
        (" ", ("VBQPPL",), _vector(), 50),
        ("q", ("UNKNOWN",), _vector(), 50),
        ("q", ("VBQPPL", "VBQPPL"), _vector(), 50),
        ("q", ("VBQPPL",), _vector()[:-1], 50),
        ("q", ("VBQPPL",), (nan,) + _vector()[1:], 50),
        ("q", ("VBQPPL",), (inf,) + _vector()[1:], 50),
        ("q", ("VBQPPL",), _vector(), 51),
    ],
)
async def test_reader_rejects_invalid_short_lived_inputs_before_opening_session(
    question: str, sources: tuple[str, ...], vector: tuple[float, ...], limit: int
) -> None:
    reader = PostgresQualityCandidateReader(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        await reader.read_candidates(question, sources, vector, limit)


def test_public_result_excludes_candidate_private_identity_and_explain_plan_data() -> None:
    identity = DocumentIdentity(
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_id=SourceId.VBQPPL,
        external_id="private-external",
        document_number_normalized="private-number",
        title="private-title",
        version_number=1,
        provenance_record_id=uuid4(),
        provenance_type=ProvenanceType.SOURCE_FETCH,
        latest_ingested=True,
    )
    candidate = CandidateEvidence(
        chunk_id=uuid4(),
        identity=identity,
        ordinal=0,
        observations=(
            LaneObservation(
                lane=RetrievalLane.SEMANTIC,
                rank=1,
                score=1.0,
                query_count=1,
                elapsed_ms=1.0,
                rows_returned=1,
            ),
        ),
        supporting_semantic_score=0.75,
        source_scope=SourceScopeObservation.NONE,
        eligible=True,
    )
    result = QualityCandidateReadResult(
        lane_candidates={RetrievalLane.SEMANTIC: (candidate,)},
        lane_metrics=(
            LaneMetrics(
                lane=RetrievalLane.SEMANTIC,
                query_count=1,
                elapsed_ms=1.0,
                sql_elapsed_ms=1.0,
                rows_returned=1,
            ),
        ),
        data_query_count=1,
        explain_query_count=0,
        query_count=1,
        transaction_elapsed_ms=1.0,
    )
    public = str(result.to_public_dict())
    serialized = str(result.model_dump())
    representation = repr(result)
    for secret in (
        str(candidate.chunk_id),
        str(identity.document_id),
        "private-external",
        "private-number",
        "private-title",
        "0.75",
    ):
        assert secret not in public
        assert secret not in serialized
        assert secret not in representation
    assert result.to_public_dict()["data_query_count"] == 1
    assert result.to_public_dict()["explain_query_count"] == 0
    assert result.to_public_dict()["requested_fts_query_mode"] == "NATURAL"
    assert result.to_public_dict()["applied_fts_query_mode"] == "NATURAL"
    assert result.to_public_dict()["fts_preparation_query_count"] == 0
    assert result.to_public_dict()["bounded_or_source_lexeme_count"] == 0
    assert result.to_public_dict()["bounded_or_selected_lexeme_count"] == 0
    assert result.to_public_dict()["bounded_or_truncated"] is False
    assert result.to_public_dict()["bounded_or_empty_query"] is False
    assert result.to_public_dict()["bounded_or_natural_fallback_used"] is False


def test_result_requires_total_query_count_to_match_data_and_explain_counts() -> None:
    with pytest.raises(ValidationError, match="data_query_count plus explain_query_count"):
        QualityCandidateReadResult(
            lane_candidates={},
            lane_metrics=(),
            data_query_count=1,
            explain_query_count=1,
            query_count=1,
            transaction_elapsed_ms=1.0,
        )


def test_bounded_or_result_metadata_is_content_free_and_fail_closed() -> None:
    result = QualityCandidateReadResult(
        lane_candidates={},
        lane_metrics=(),
        data_query_count=5,
        explain_query_count=0,
        query_count=5,
        transaction_elapsed_ms=1.0,
        requested_fts_query_mode=FTSQueryMode.BOUNDED_OR,
        applied_fts_query_mode=FTSQueryMode.BOUNDED_OR,
        fts_preparation_query_count=1,
        fts_preparation_elapsed_ms=0.5,
        bounded_or_selected_lexeme_count=32,
        bounded_or_source_lexeme_count=33,
        bounded_or_truncated=True,
    )

    public = result.to_public_dict()
    assert public["requested_fts_query_mode"] == "BOUNDED_OR"
    assert public["applied_fts_query_mode"] == "BOUNDED_OR"
    assert public["bounded_or_selected_lexeme_count"] == 32
    assert public["bounded_or_source_lexeme_count"] == 33
    assert public["bounded_or_truncated"] is True
    assert public["bounded_or_empty_query"] is False
    assert public["bounded_or_natural_fallback_used"] is False
    assert "or_tsquery" not in public
    assert "natural_tsquery_text" not in public

    with pytest.raises(ValidationError, match="fail closed"):
        QualityCandidateReadResult(
            lane_candidates={},
            lane_metrics=(),
            data_query_count=5,
            explain_query_count=0,
            query_count=5,
            transaction_elapsed_ms=1.0,
            requested_fts_query_mode=FTSQueryMode.BOUNDED_OR,
            applied_fts_query_mode=FTSQueryMode.NATURAL,
            fts_preparation_query_count=1,
            fts_preparation_elapsed_ms=0.5,
        )


def test_natural_result_rejects_bounded_or_preparation_or_shape_metadata() -> None:
    with pytest.raises(ValidationError, match="NATURAL reads must report zero"):
        QualityCandidateReadResult(
            lane_candidates={},
            lane_metrics=(),
            data_query_count=1,
            explain_query_count=0,
            query_count=1,
            transaction_elapsed_ms=1.0,
            fts_preparation_query_count=1,
            fts_preparation_elapsed_ms=0.5,
        )


def test_bounded_or_empty_query_metadata_requires_no_natural_fallback() -> None:
    result = QualityCandidateReadResult(
        lane_candidates={},
        lane_metrics=(),
        data_query_count=4,
        explain_query_count=0,
        query_count=4,
        transaction_elapsed_ms=1.0,
        requested_fts_query_mode=FTSQueryMode.BOUNDED_OR,
        applied_fts_query_mode=FTSQueryMode.BOUNDED_OR,
        fts_preparation_query_count=1,
        fts_preparation_elapsed_ms=0.5,
        bounded_or_empty_query=True,
    )
    assert result.to_public_dict()["bounded_or_empty_query"] is True

    with pytest.raises(ValidationError, match="empty-query state"):
        QualityCandidateReadResult(
            lane_candidates={},
            lane_metrics=(),
            data_query_count=4,
            explain_query_count=0,
            query_count=4,
            transaction_elapsed_ms=1.0,
            requested_fts_query_mode=FTSQueryMode.BOUNDED_OR,
            applied_fts_query_mode=FTSQueryMode.BOUNDED_OR,
            fts_preparation_query_count=1,
            fts_preparation_elapsed_ms=0.5,
            bounded_or_empty_query=False,
        )


def test_bounded_or_control_escapes_deduplicates_and_caps_at_32_lexemes() -> None:
    tsquery = "'it''s' & 'repeat' & 'repeat' & " + " & ".join(
        f"'term{number}'" for number in range(32)
    )

    control, count, truncated = build_or_tsquery(tsquery)

    assert control.startswith("'it''s' | 'repeat'")
    assert control.count("'repeat'") == 1
    assert count == 34
    assert truncated is True
    assert control.count("|") == 31


def test_natural_fts_mode_remains_the_default_and_bounded_or_uses_to_tsquery() -> None:
    reader = PostgresQualityCandidateReader(None)  # type: ignore[arg-type]

    assert reader._validate_fts_query_mode("NATURAL") is FTSQueryMode.NATURAL  # noqa: SLF001
    assert reader._validate_fts_query_mode(FTSQueryMode.BOUNDED_OR) is FTSQueryMode.BOUNDED_OR  # noqa: SLF001
    assert str(reader._content_statement(("VBQPPL",), 50)) == str(  # noqa: SLF001
        reader._content_statement(("VBQPPL",), 50, FTSQueryMode.NATURAL)  # noqa: SLF001
    )
    assert "websearch_to_tsquery" in str(  # noqa: SLF001
        reader._content_statement(("VBQPPL",), 50)  # noqa: SLF001
    )
    assert "to_tsquery" in str(  # noqa: SLF001
        reader._title_statement(("VBQPPL",), 50, FTSQueryMode.BOUNDED_OR)  # noqa: SLF001
    )
    with pytest.raises(ValueError, match="NATURAL or BOUNDED_OR"):
        reader._validate_fts_query_mode("runtime")  # noqa: SLF001


def test_reader_keeps_title_observation_score_separate_from_semantic_support() -> None:
    chunk_id, document_id, version_id, provenance_id = (uuid4(), uuid4(), uuid4(), uuid4())
    row = (
        chunk_id,
        0,
        document_id,
        version_id,
        "VBQPPL",
        "private-external",
        None,
        None,
        1,
        "Quyết định",
        "Cơ quan ban hành",
        "Còn hiệu lực",
        provenance_id,
        "source_fetch",
        "STRICT_TLS",
        0.75,
    )
    semantic = PostgresQualityCandidateReader._candidates([row], RetrievalLane.SEMANTIC, 1, 1.0, 1)[
        0
    ]
    content = PostgresQualityCandidateReader._candidates(
        [row], RetrievalLane.CONTENT_FTS, 1, 1.0, 1
    )[0]
    title = PostgresQualityCandidateReader._candidates(
        [row], RetrievalLane.TITLE_FTS, 2, 1.0, 1, scores={version_id: (1, 0.25)}
    )[0]
    assert semantic.supporting_semantic_score == semantic.observations[0].score == 0.75
    assert content.supporting_semantic_score is None
    assert title.observations[0].lane is RetrievalLane.TITLE_FTS
    assert title.observations[0].score == 0.25
    assert title.supporting_semantic_score == 0.75


def test_buffer_parser_keeps_only_numeric_root_counters() -> None:
    summary = PostgresQualityCandidateReader._buffer_summary(
        [{"Plan": {"Shared Hit Blocks": 3, "Shared Read Blocks": 2, "Temp Read Blocks": 1}}]
    )
    assert summary.shared_hit == 3
    assert summary.shared_read == 2
    assert summary.temp_read == 1
    assert summary.temp_written == 0
