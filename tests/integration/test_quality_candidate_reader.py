"""Opt-in PostgreSQL coverage for the Phase-B2 evaluation-only candidate reader."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.quality_candidate_reader import (
    FTSQueryMode,
    PostgresQualityCandidateReader,
)
from legal_chatbot.retrieval.quality_repair.models import RetrievalLane
from legal_chatbot.semantic.constants import SEMANTIC_PROFILE_ID

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _vector() -> list[float]:
    return [1.0] + [0.0] * 383


async def _seed(
    session: AsyncSession,
    *,
    source_id: str = "VBQPPL",
    document_id: UUID | None = None,
    version_number: int = 1,
    strict: bool = True,
    exact_profile: bool = True,
    content: str = "unrelated body",
    title: str | None = None,
) -> tuple[UUID, UUID, UUID]:
    document_id = document_id or uuid4()
    version_id, chunk_id = uuid4(), uuid4()
    if version_number == 1:
        session.add(
            LegalDocument(id=document_id, source_id=source_id, external_id=f"b2-{document_id}")
        )
    digest = _digest(str(version_id))
    session.add(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            title=title,
            raw_html=content,
            normalized_text=content,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="quality-b2",
            normalized_block_count=1,
        )
    )
    session.add(
        SourceProvenanceRecord(
            document_version_id=version_id,
            provenance_type="source_fetch",
            source_id=source_id,
            transport="test",
            operation="quality-b2",
            retrieved_at=datetime.now(UTC),
            tls_verified=strict,
        )
    )
    session.add(
        DocumentChunk(
            id=chunk_id,
            document_version_id=version_id,
            ordinal=0,
            content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(str(chunk_id)),
            chunker_version="quality-b2",
        )
    )
    session.add(
        ChunkEmbedding(
            document_chunk_id=chunk_id,
            embedding=_vector(),
            embedding_model_id=SEMANTIC_PROFILE_ID if exact_profile else "wrong-profile",
            embedding_kind="semantic",
            dimension=384,
            embedding_input_sha256=_digest(f"embedding-{chunk_id}"),
        )
    )
    return document_id, version_id, chunk_id


@pytest.mark.asyncio
async def test_quality_candidate_reader_lanes_are_read_only_exact_and_bounded() -> None:
    engine = create_engine(Settings())  # type: ignore[call-arg]
    sessions = create_session_factory(engine)
    document_ids: list[UUID] = []
    sql_events: list[str] = []

    def record_sql(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        sql_events.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        async with sessions.begin() as session:
            semantic_doc, _, semantic_chunk = await _seed(session)
            content_doc, _, content_chunk = await _seed(
                session, content="qualitycandidatephrase in body"
            )
            title_doc, _, title_chunk = await _seed(
                session,
                title="qualitycandidatephrase only in title",
                content="a supporting child without the query token",
            )
            old_doc, _, old_chunk = await _seed(
                session, content="qualitycandidatephrase old version"
            )
            await _seed(
                session,
                document_id=old_doc,
                version_number=2,
                content="latest version does not match",
            )
            inactive_doc, _, inactive_chunk = await _seed(
                session, source_id="VNU", content="qualitycandidatephrase inactive"
            )
            untrusted_doc, _, untrusted_chunk = await _seed(
                session, strict=False, content="qualitycandidatephrase untrusted"
            )
            wrong_doc, _, wrong_chunk = await _seed(
                session, exact_profile=False, content="qualitycandidatephrase wrong profile"
            )
            document_ids.extend(
                (
                    semantic_doc,
                    content_doc,
                    title_doc,
                    old_doc,
                    inactive_doc,
                    untrusted_doc,
                    wrong_doc,
                )
            )

        async with sessions() as session:
            before_runs = await session.scalar(select(func.count()).select_from(RetrievalRun))
            before_citations = await session.scalar(
                select(func.count()).select_from(CitationRecord)
            )

        reader = PostgresQualityCandidateReader(sessions)
        sql_events.clear()
        result = await reader.read_candidates(
            "qualitycandidatephrase", ("VBQPPL",), tuple(_vector()), diagnostic_limit=50
        )
        assert result.query_count == 4
        assert (result.data_query_count, result.explain_query_count) == (4, 0)
        assert [metric.query_count for metric in result.lane_metrics] == [1, 1, 2]
        assert set(result.lane_candidates) == set(RetrievalLane)
        semantic_ids = {
            candidate.chunk_id for candidate in result.lane_candidates[RetrievalLane.SEMANTIC]
        }
        content_ids = {
            candidate.chunk_id for candidate in result.lane_candidates[RetrievalLane.CONTENT_FTS]
        }
        title_ids = {
            candidate.chunk_id for candidate in result.lane_candidates[RetrievalLane.TITLE_FTS]
        }
        assert semantic_chunk in semantic_ids
        assert content_chunk in content_ids
        assert title_chunk in title_ids
        assert old_chunk not in content_ids
        assert inactive_chunk not in content_ids
        assert untrusted_chunk not in content_ids
        assert wrong_chunk not in semantic_ids
        semantic_candidate = next(
            candidate
            for candidate in result.lane_candidates[RetrievalLane.SEMANTIC]
            if candidate.chunk_id == semantic_chunk
        )
        title_candidate = next(
            candidate
            for candidate in result.lane_candidates[RetrievalLane.TITLE_FTS]
            if candidate.chunk_id == title_chunk
        )
        assert (
            semantic_candidate.supporting_semantic_score == semantic_candidate.observations[0].score
        )
        assert all(
            candidate.supporting_semantic_score is None
            for candidate in result.lane_candidates[RetrievalLane.CONTENT_FTS]
        )
        assert title_candidate.observations[0].lane is RetrievalLane.TITLE_FTS
        assert title_candidate.observations[0].score is not None
        assert title_candidate.supporting_semantic_score is not None
        assert isfinite(title_candidate.supporting_semantic_score)
        assert title_candidate.observations[0].score != title_candidate.supporting_semantic_score
        assert all(
            len(candidate.observations) == 1
            for lane in result.lane_candidates.values()
            for candidate in lane
        )
        assert all(
            candidate.observations[0].lane is RetrievalLane.TITLE_FTS
            for candidate in result.lane_candidates[RetrievalLane.TITLE_FTS]
        )
        assert "SET LOCAL enable_indexscan = off" in sql_events
        assert "SET LOCAL enable_bitmapscan = off" in sql_events
        semantic_index = sql_events.index("SET LOCAL enable_indexscan = off")
        restore_index = sql_events.index("SET LOCAL enable_indexscan = on")
        assert semantic_index < restore_index

        sql_events.clear()
        explained = await reader.read_candidates(
            "qualitycandidatephrase", ("VBQPPL",), tuple(_vector()), explain=True
        )
        assert explained.query_count == 8
        assert (explained.data_query_count, explained.explain_query_count) == (4, 4)
        assert all(metric.buffers.shared_hit >= 0 for metric in explained.lane_metrics)
        assert any("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in item for item in sql_events)
        indexscan_off = [
            index
            for index, item in enumerate(sql_events)
            if item == "SET LOCAL enable_indexscan = off"
        ]
        indexscan_on = [
            index
            for index, item in enumerate(sql_events)
            if item == "SET LOCAL enable_indexscan = on"
        ]
        assert len(indexscan_off) == len(indexscan_on) == 2
        assert indexscan_off[0] < indexscan_on[0] < indexscan_off[1] < indexscan_on[1]
        title_support_events = [
            index for index, item in enumerate(sql_events) if "title_support" in item.lower()
        ]
        assert title_support_events
        assert all(indexscan_off[1] < index < indexscan_on[1] for index in title_support_events)
        fts_events = [
            index
            for index, item in enumerate(sql_events)
            if "search_vector @@" in item.lower() or "title_search_vector @@" in item.lower()
        ]
        assert fts_events
        assert all(indexscan_on[0] < index < indexscan_off[1] for index in fts_events)

        no_title_normal = await reader.read_candidates(
            "notitlematchphaseb2", ("VBQPPL",), tuple(_vector())
        )
        assert (no_title_normal.data_query_count, no_title_normal.explain_query_count) == (3, 0)
        assert no_title_normal.query_count == 3

        no_title = await reader.read_candidates(
            "notitlematchphaseb2", ("VBQPPL",), tuple(_vector()), explain=True
        )
        assert no_title.query_count == 6
        assert (no_title.data_query_count, no_title.explain_query_count) == (3, 3)
        assert [metric.query_count for metric in no_title.lane_metrics] == [2, 2, 2]

        async with sessions() as session:
            assert (
                await session.scalar(select(func.count()).select_from(RetrievalRun)) == before_runs
            )
            assert (
                await session.scalar(select(func.count()).select_from(CitationRecord))
                == before_citations
            )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)
        async with sessions.begin() as session:
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_bounded_or_prepares_once_and_recovers_each_fts_lane_without_writes() -> None:
    engine = create_engine(Settings())  # type: ignore[call-arg]
    sessions = create_session_factory(engine)
    document_ids: list[UUID] = []
    sql_events: list[str] = []

    def record_sql(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: object,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        sql_events.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        async with sessions.begin() as session:
            content_doc, _, content_chunk = await _seed(
                session, content="phaseb2orcontentmarker"
            )
            title_doc, _, title_chunk = await _seed(
                session,
                title="phaseb2ortitlemarker",
                content="supporting child without either FTS marker",
            )
            untrusted_doc, _, untrusted_chunk = await _seed(
                session, content="phaseb2orcontentmarker", strict=False
            )
            inactive_doc, _, inactive_chunk = await _seed(
                session, source_id="VNU", content="phaseb2orcontentmarker"
            )
            document_ids.extend((content_doc, title_doc, untrusted_doc, inactive_doc))

        async with sessions() as session:
            before = (
                int((await session.scalar(select(func.count()).select_from(RetrievalRun))) or 0),
                int((await session.scalar(select(func.count()).select_from(CitationRecord))) or 0),
            )

        reader = PostgresQualityCandidateReader(sessions)
        question = "phaseb2orcontentmarker phaseb2ortitlemarker"
        natural_default = await reader.read_candidates(question, ("VBQPPL",), tuple(_vector()))
        natural_explicit = await reader.read_candidates(
            question, ("VBQPPL",), tuple(_vector()), fts_query_mode="NATURAL"
        )
        assert natural_default.fts_preparation_query_count == 0
        assert natural_default.fts_preparation_elapsed_ms == 0
        assert natural_default.requested_fts_query_mode is FTSQueryMode.NATURAL
        assert natural_default.applied_fts_query_mode is FTSQueryMode.NATURAL
        assert (
            natural_default.bounded_or_selected_lexeme_count,
            natural_default.bounded_or_source_lexeme_count,
            natural_default.bounded_or_truncated,
            natural_default.bounded_or_empty_query,
            natural_default.bounded_or_natural_fallback_used,
        ) == (0, 0, False, False, False)
        assert natural_default.data_query_count == natural_explicit.data_query_count == 3
        for lane in (RetrievalLane.CONTENT_FTS, RetrievalLane.TITLE_FTS):
            assert (
                natural_default.lane_candidates[lane]
                == natural_explicit.lane_candidates[lane]
                == ()
            )

        sql_events.clear()
        bounded = await reader.read_candidates(
            question,
            ("VBQPPL",),
            tuple(_vector()),
            fts_query_mode=FTSQueryMode.BOUNDED_OR,
        )
        assert (bounded.data_query_count, bounded.explain_query_count, bounded.query_count) == (
            5,
            0,
            5,
        )
        assert bounded.fts_preparation_query_count == 1
        assert bounded.fts_preparation_elapsed_ms >= 0
        assert bounded.requested_fts_query_mode is FTSQueryMode.BOUNDED_OR
        assert bounded.applied_fts_query_mode is FTSQueryMode.BOUNDED_OR
        assert (
            bounded.bounded_or_selected_lexeme_count,
            bounded.bounded_or_source_lexeme_count,
            bounded.bounded_or_truncated,
            bounded.bounded_or_empty_query,
            bounded.bounded_or_natural_fallback_used,
        ) == (2, 2, False, False, False)
        content_ids = {
            candidate.chunk_id for candidate in bounded.lane_candidates[RetrievalLane.CONTENT_FTS]
        }
        title_ids = {
            candidate.chunk_id for candidate in bounded.lane_candidates[RetrievalLane.TITLE_FTS]
        }
        assert content_chunk in content_ids
        assert title_chunk in title_ids
        assert untrusted_chunk not in content_ids
        assert inactive_chunk not in content_ids
        title_candidate = next(
            candidate
            for candidate in bounded.lane_candidates[RetrievalLane.TITLE_FTS]
            if candidate.chunk_id == title_chunk
        )
        assert title_candidate.supporting_semantic_score is not None
        assert sum("websearch_to_tsquery" in item.lower() for item in sql_events) == 1
        fts_events = [
            item
            for item in sql_events
            if "search_vector @@" in item.lower() or "title_search_vector @@" in item.lower()
        ]
        assert len(fts_events) == 2
        assert all("to_tsquery(" in item.lower() for item in fts_events)
        assert not any(
            item.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            for item in sql_events
        )
        safe_result = str(bounded.to_public_dict()) + repr(bounded) + str(bounded.model_dump())
        assert question not in safe_result
        assert "phaseb2orcontentmarker" not in safe_result
        assert "phaseb2ortitlemarker" not in safe_result

        empty_bounded = await reader.read_candidates(
            "!!!",
            ("VBQPPL",),
            tuple(_vector()),
            fts_query_mode=FTSQueryMode.BOUNDED_OR,
        )
        assert (
            empty_bounded.data_query_count,
            empty_bounded.explain_query_count,
            empty_bounded.query_count,
        ) == (4, 0, 4)
        assert empty_bounded.requested_fts_query_mode is FTSQueryMode.BOUNDED_OR
        assert empty_bounded.applied_fts_query_mode is FTSQueryMode.BOUNDED_OR
        assert (
            empty_bounded.bounded_or_selected_lexeme_count,
            empty_bounded.bounded_or_source_lexeme_count,
            empty_bounded.bounded_or_truncated,
            empty_bounded.bounded_or_empty_query,
            empty_bounded.bounded_or_natural_fallback_used,
        ) == (0, 0, False, True, False)
        assert empty_bounded.lane_candidates[RetrievalLane.CONTENT_FTS] == ()
        assert empty_bounded.lane_candidates[RetrievalLane.TITLE_FTS] == ()

        sql_events.clear()
        explained = await reader.read_candidates(
            question,
            ("VBQPPL",),
            tuple(_vector()),
            explain=True,
            fts_query_mode=FTSQueryMode.BOUNDED_OR,
        )
        assert (
            explained.data_query_count,
            explained.explain_query_count,
            explained.query_count,
        ) == (
            5,
            4,
            9,
        )
        assert explained.fts_preparation_query_count == 1
        assert explained.fts_preparation_elapsed_ms >= 0
        assert [metric.query_count for metric in explained.lane_metrics] == [2, 2, 4]
        assert sum("websearch_to_tsquery" in item.lower() for item in sql_events) == 1
        assert sum("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in item for item in sql_events) == 4

        async with sessions() as session:
            after = (
                int((await session.scalar(select(func.count()).select_from(RetrievalRun))) or 0),
                int((await session.scalar(select(func.count()).select_from(CitationRecord))) or 0),
            )
        assert after == before
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)
        async with sessions.begin() as session:
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()
