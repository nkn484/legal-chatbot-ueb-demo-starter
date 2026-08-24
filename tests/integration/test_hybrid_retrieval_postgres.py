"""Opt-in PostgreSQL evidence for exact semantic/hybrid retrieval Gate 3."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.hybrid_retrieval_repository import PostgresHybridRetrievalRepository
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.retrieval.models import RetrievalDecision, RetrievalReason, RetrievalRequest
from legal_chatbot.semantic.constants import SEMANTIC_PROFILE_ID
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode
from legal_chatbot.semantic.models import SemanticEmbeddingBatch

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _vector(first: float = 1.0) -> list[float]:
    return [first] + [0.0] * 383


class _Embedder:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        del text
        self.events.append("embed")
        if self.fail:
            raise SemanticError(SemanticErrorCode.MODEL_UNAVAILABLE)
        return SemanticEmbeddingBatch(vectors=(tuple(_vector()),))

    async def embed_documents(self, texts: object) -> SemanticEmbeddingBatch:
        raise AssertionError(texts)


async def _seed_chunk(
    session: object,
    *,
    source_id: str,
    version_number: int = 1,
    strict: bool = True,
    semantic: bool = True,
    semantic_model: str = SEMANTIC_PROFILE_ID,
    content: str = "hybridgate lexical token",
) -> tuple[object, object, object]:
    document_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
    session.add(  # type: ignore[attr-defined]
        LegalDocument(id=document_id, source_id=source_id, external_id=f"gate-{document_id}")
    )
    digest = _digest(str(version_id))
    session.add(  # type: ignore[attr-defined]
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            raw_html=content,
            normalized_text=content,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="gate3",
            normalized_block_count=1,
        )
    )
    session.add(  # type: ignore[attr-defined]
        SourceProvenanceRecord(
            document_version_id=version_id,
            provenance_type="source_fetch",
            source_id=source_id,
            transport="test",
            operation="gate3",
            retrieved_at=datetime.now(UTC),
            tls_verified=strict,
        )
    )
    session.add(  # type: ignore[attr-defined]
        DocumentChunk(
            id=chunk_id,
            document_version_id=version_id,
            ordinal=0,
            content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(str(chunk_id)),
            chunker_version="gate3",
        )
    )
    session.add(  # type: ignore[attr-defined]
        ChunkEmbedding(
            document_chunk_id=chunk_id,
            embedding=_vector(),
            embedding_model_id="local-hash-v1",
            embedding_kind="demo_non_semantic",
            dimension=384,
            embedding_input_sha256=_digest(f"local-{chunk_id}"),
        )
    )
    if semantic:
        session.add(  # type: ignore[attr-defined]
            ChunkEmbedding(
                document_chunk_id=chunk_id,
                embedding=_vector(),
                embedding_model_id=semantic_model,
                embedding_kind="semantic",
                dimension=384,
                embedding_input_sha256=_digest(f"semantic-{chunk_id}"),
            )
        )
    return document_id, version_id, chunk_id


@pytest.mark.asyncio
async def test_hybrid_postgres_exact_profile_scope_scores_fallback_and_scan_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seed local-hash and excluded rows, then prove exact semantic Gate-3 behavior."""

    engine = create_engine(Settings())
    sessions = create_session_factory(engine)
    document_ids: list[object] = []
    run_ids: list[object] = []
    events: list[str] = []
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
            active_document, _, active_chunk = await _seed_chunk(session, source_id="GATE3")
            local_only, _, _ = await _seed_chunk(session, source_id="GATE3", semantic=False)
            inactive, _, _ = await _seed_chunk(session, source_id="INACTIVE")
            untrusted, _, _ = await _seed_chunk(session, source_id="GATE3", strict=False)
            wrong_model, _, _ = await _seed_chunk(
                session, source_id="INACTIVE", semantic_model="wrong-profile"
            )
            document_ids.extend((active_document, local_only, inactive, untrusted, wrong_model))

        assert not await PostgresHybridRetrievalRepository.coverage_complete_for(
            sessions, ("GATE3",)
        )
        async with sessions.begin() as session:
            # Only the active strict local-only chunk receives its exact profile row.
            local_chunk = await session.scalar(
                select(DocumentChunk.id)
                .join(DocumentVersion)
                .where(DocumentVersion.document_id == local_only)
            )
            assert local_chunk is not None
            session.add(
                ChunkEmbedding(
                    document_chunk_id=local_chunk,
                    embedding=_vector(),
                    embedding_model_id=SEMANTIC_PROFILE_ID,
                    embedding_kind="semantic",
                    dimension=384,
                    embedding_input_sha256=_digest(f"complete-{local_chunk}"),
                )
            )
        # Untrusted/inactive wrong-profile rows do not participate in active strict coverage.
        assert await PostgresHybridRetrievalRepository.coverage_complete_for(sessions, ("GATE3",))

        repository = PostgresHybridRetrievalRepository(
            sessions, ("GATE3",), _Embedder(events), mode="semantic"
        )
        sql_events.clear()
        result = await repository.retrieve_and_persist(
            RetrievalRequest(query="hybridgate", top_k=2)
        )
        run_ids.append(result.retrieval_run_id)
        assert result.decision is RetrievalDecision.EVIDENCE_AVAILABLE
        assert result.reason is RetrievalReason.SEMANTIC_EVIDENCE_AVAILABLE
        assert active_chunk in {candidate.document_chunk_id for candidate in result.candidates}
        assert all(candidate.lexical_score is None for candidate in result.candidates)
        assert all(candidate.semantic_score is not None for candidate in result.candidates)
        assert events == ["embed"]
        assert sql_events
        assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in sql_events[1]
        assert "SET LOCAL enable_indexscan = off" in sql_events
        assert "SET LOCAL enable_bitmapscan = off" in sql_events
        assert "SET LOCAL enable_indexscan = on" in sql_events
        assert "SET LOCAL enable_bitmapscan = on" in sql_events

        fallback = PostgresHybridRetrievalRepository(
            sessions, ("GATE3",), _Embedder([], fail=True), mode="hybrid"
        )
        fallback_result = await fallback.retrieve_and_persist(RetrievalRequest(query="hybridgate"))
        run_ids.append(fallback_result.retrieval_run_id)
        assert fallback_result.reason is RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE
        async with sessions() as session:
            run = await session.scalar(
                select(RetrievalRun).where(RetrievalRun.id == result.retrieval_run_id)
            )
            assert run is not None and run.strategy_version == "v4_semantic_exact"
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)
        async with sessions.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()
