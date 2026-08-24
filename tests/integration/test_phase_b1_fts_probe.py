"""Opt-in PostgreSQL coverage for the standalone, read-only Phase-B1 FTS probe."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.diagnostics.phase_b1_fts_probe import FTSProbeConfig, ProbeCase, probe_fts_cases
from legal_chatbot.diagnostics.phase_b1_retrieval_engine import (
    LaneEvidence,
    RootCauseCode,
    classify_lane,
)
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.quality_candidate_reader import PostgresQualityCandidateReader

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


async def _seed(
    session,
    *,
    number: str,
    title: str,
    content: str,
    strict: bool = True,
) -> UUID:
    document_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
    digest = _digest(str(version_id))
    session.add(
        LegalDocument(
            id=document_id, source_id="VBQPPL", external_id=f"fts-probe-{document_id}"
        )
    )
    await session.flush()
    session.add(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            document_number=number,
            document_number_normalized=number,
            title=title,
            raw_html=content,
            normalized_text=content,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="fts-probe-test",
            normalized_block_count=1,
        )
    )
    await session.flush()
    session.add(
        DocumentChunk(
            id=chunk_id,
            document_version_id=version_id,
            ordinal=0,
            content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(str(chunk_id)),
            chunker_version="fts-probe-test",
        )
    )
    session.add(
        SourceProvenanceRecord(
            document_version_id=version_id,
            provenance_type="source_fetch",
            source_id="VBQPPL",
            transport="test",
            operation="fts-probe-test",
            retrieved_at=datetime.now(UTC),
            tls_verified=strict,
        )
    )
    await session.flush()
    return document_id


@pytest.mark.asyncio
async def test_probe_is_read_only_and_or_control_finds_single_term_title_and_body_matches() -> None:
    engine = create_engine(Settings())  # type: ignore[call-arg]
    sessions = create_session_factory(engine)
    document_ids: list[UUID] = []
    try:
        async with sessions.begin() as session:
            document_ids.append(
                await _seed(
                    session,
                    number="FTS-TITLE-01",
                    title="phaseb1titlemarker",
                    content="unrelated content",
                )
            )
            document_ids.append(
                await _seed(
                    session,
                    number="FTS-BODY-01",
                    title="unrelated title",
                    content="phaseb1bodymarker",
                )
            )
            document_ids.append(
                await _seed(
                    session,
                    number="FTS-UNTRUSTED-01",
                    title="unrelated title",
                    content="phaseb1bodymarker",
                    strict=False,
                )
            )

        async with sessions() as session:
            before = (
                int((await session.scalar(select(func.count()).select_from(RetrievalRun))) or 0),
                int((await session.scalar(select(func.count()).select_from(CitationRecord))) or 0),
            )

        result = await probe_fts_cases(
            sessions,
            PostgresQualityCandidateReader(sessions),
            (
                ProbeCase(
                    "Q01",
                    "phaseb1titlemarker phaseb1bodymarker",
                    ("FTS-TITLE-01", "FTS-BODY-01"),
                ),
                ProbeCase("Q02", "phaseb1-no-match-marker", ("FTS-BODY-01",)),
                ProbeCase("Q03", "phaseb1bodymarker", ("FTS-BODY-01",)),
            ),
            config=FTSProbeConfig(),
        )

        first, no_match, filtered = result.cases
        assert first.content.natural_filtered_rows == 0
        assert first.title.natural_filtered_rows == 0
        assert first.content.or_filtered_expected is True
        assert first.title.or_filtered_expected is True
        for lane, gin_index_valid in (
            (no_match.content, result.inventory.content_gin_valid),
            (no_match.title, result.inventory.title_gin_valid),
        ):
            # The OR control can return noisy, unrelated top-50 rows.  Only the
            # post-score expected-identity flag determines no-match evidence.
            assert lane.or_filtered_rows >= 0
            assert lane.or_filtered_expected is False
            assert (
                classify_lane(
                    LaneEvidence(
                        config_matches_simple=result.inventory.config_matches_simple,
                        gin_index_valid=gin_index_valid,
                        natural_unfiltered_rows=lane.natural_unfiltered_rows,
                        natural_filtered_rows=lane.natural_filtered_rows,
                        natural_unfiltered_expected=lane.natural_unfiltered_expected,
                        natural_filtered_expected=lane.natural_filtered_expected,
                        collapsed_expected=False,
                        fused_expected=False,
                        or_expected=lane.or_filtered_expected,
                    )
                )
                is RootCauseCode.FTS_NO_MATCH
            )
        assert filtered.content.natural_unfiltered_rows == 2
        assert filtered.content.natural_filtered_rows == 1
        assert filtered.content.natural_filtered_expected is True
        assert result.inventory.config_matches_simple is True
        assert result.inventory.content_gin_valid is True
        assert result.inventory.title_gin_valid is True
        assert result.data_query_count == 26
        capability_controls = sum(
            lane.index_capability_control is not None
            for case in result.cases
            for lane in (case.content, case.title)
        )
        assert result.explain_query_count == 12 + capability_controls
        assert all(
            lane.index_capability_used is None
            or lane.index_capability_used == (
                "ix_document_chunks_search_vector_gin" in lane.index_capability_control.index_names
                or "ix_document_versions_title_search_vector_gin"
                in lane.index_capability_control.index_names
            )
            for case in result.cases
            for lane in (case.content, case.title)
            if lane.index_capability_control is not None
        )

        async with sessions() as session:
            after = (
                int((await session.scalar(select(func.count()).select_from(RetrievalRun))) or 0),
                int((await session.scalar(select(func.count()).select_from(CitationRecord))) or 0),
            )
        assert after == before
    finally:
        if document_ids:
            async with sessions.begin() as session:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()
