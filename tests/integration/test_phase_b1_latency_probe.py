"""Opt-in PostgreSQL coverage for the read-only Phase-B1 latency probe."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.diagnostics.phase_b1_latency_probe import (
    LatencyProbeCase,
    probe_latency_cases,
)
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.quality_candidate_reader import PostgresQualityCandidateReader
from legal_chatbot.semantic.constants import SEMANTIC_PROFILE_ID
from legal_chatbot.semantic.models import SemanticEmbeddingBatch

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _fixed_vector() -> list[float]:
    return [1.0] + [0.0] * 383


class _FixedVectorEmbedder:
    """Avoid model loading: the probe only needs its 384-dimensional port result."""

    async def embed_query(self, _question: str) -> SemanticEmbeddingBatch:
        return SemanticEmbeddingBatch(vectors=(tuple(_fixed_vector()),))


async def _seed_synthetic_semantic_row(session) -> UUID:
    document_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
    content = "latencyprobecontenttoken"
    digest = _digest(str(document_id))
    session.add(
        LegalDocument(
            id=document_id,
            source_id="VBQPPL",
            external_id=f"latency-{document_id}",
        )
    )
    await session.flush()
    session.add(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            title="latencyprobetitletoken",
            raw_html=content,
            normalized_text=content,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="latency-probe-test",
            normalized_block_count=1,
        )
    )
    await session.flush()
    session.add(
        SourceProvenanceRecord(
            document_version_id=version_id,
            provenance_type="source_fetch",
            source_id="VBQPPL",
            transport="test",
            operation="latency-probe-test",
            retrieved_at=datetime.now(UTC),
            tls_verified=True,
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
            chunker_version="latency-probe-test",
        )
    )
    await session.flush()
    session.add(
        ChunkEmbedding(
            document_chunk_id=chunk_id,
            embedding=_fixed_vector(),
            embedding_model_id=SEMANTIC_PROFILE_ID,
            embedding_kind="semantic",
            dimension=384,
            embedding_input_sha256=_digest(f"embedding-{chunk_id}"),
        )
    )
    await session.flush()
    return document_id


@pytest.mark.asyncio
async def test_latency_probe_uses_fixed_vectors_is_read_only_and_records_safe_plan_evidence(
) -> None:
    engine = create_engine(Settings())  # type: ignore[call-arg]
    sessions = create_session_factory(engine)
    sql_events: list[str] = []
    document_id: UUID | None = None

    def record_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        sql_events.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        async with sessions.begin() as session:
            document_id = await _seed_synthetic_semantic_row(session)
        async with sessions() as session:
            before = (
                int((await session.scalar(select(func.count(RetrievalRun.id)))) or 0),
                int((await session.scalar(select(func.count(CitationRecord.id)))) or 0),
            )

        sql_events.clear()
        result = await probe_latency_cases(
            sessions,
            PostgresQualityCandidateReader(sessions),
            _FixedVectorEmbedder(),
            (LatencyProbeCase("fixed-vector-case", "latencyprobetitletoken"),),
        )

        case = result.cases[0]
        assert result.counts.embedding_call_count == 2
        assert result.counts.timed_embedding_call_count == 1
        assert result.counts.database_warmup_call_count == 3
        assert result.counts.database_warmup_data_query_count >= 7
        assert result.counts.database_warmup_explain_query_count >= 3
        assert result.counts.phase4_exact_path_count == 1
        assert case.phase4.data_query_count == 1
        assert case.diagnostic.data_query_count >= 3
        assert case.diagnostic_with_explain.data_query_count == case.diagnostic.data_query_count
        assert case.diagnostic_with_explain.explain_query_count == case.diagnostic.data_query_count
        assert case.diagnostic_with_explain.explain_overhead_ms >= 0
        assert result.counts.duplicate_query_count == case.diagnostic_with_explain.data_query_count
        assert [item.requested_limit for item in case.plans] == [8, 50, 50]
        assert all(item.cosine_operator_known and item.limit_evidence for item in case.plans)
        assert all(isinstance(item.hnsw_index_available, bool) for item in case.plans)
        # A small fixture is not required to select the HNSW index; actual selection is recorded.
        assert all(isinstance(item.hnsw_index_used, bool) for item in case.plans)
        assert any("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)" in sql for sql in sql_events)
        assert any("SET LOCAL enable_indexscan = off" in sql for sql in sql_events)
        assert any("SET LOCAL enable_indexscan = on" in sql for sql in sql_events)
        assert not any(
            sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in sql_events
        )
        safe_result = json.dumps(result.to_public_dict())
        assert "latencyprobetitletoken" not in safe_result
        assert "latencyprobecontenttoken" not in safe_result

        async with sessions() as session:
            after = (
                int((await session.scalar(select(func.count(RetrievalRun.id)))) or 0),
                int((await session.scalar(select(func.count(CitationRecord.id)))) or 0),
            )
        assert after == before
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)
        if document_id is not None:
            async with sessions.begin() as session:
                await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
        await engine.dispose()
