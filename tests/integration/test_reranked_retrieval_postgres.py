"""Opt-in PostgreSQL evidence for bounded reranked exact-semantic retrieval."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

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
from legal_chatbot.documents.reranked_semantic_repository import PostgresRerankedSemanticRepository
from legal_chatbot.reranking.models import RerankResult
from legal_chatbot.retrieval.models import RetrievalRequest
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


def _vector() -> list[float]:
    return [1.0] + [0.0] * 383


class _Embedder:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        del text
        self.events.append("embed")
        return SemanticEmbeddingBatch(vectors=(tuple(_vector()),))

    async def embed_documents(self, texts):
        raise AssertionError(texts)


class _Reranker:
    def __init__(self, events: list[str], *, invalid: bool = False) -> None:
        self.events = events
        self.invalid = invalid

    async def rerank(self, request):
        self.events.append("rerank")
        ids = tuple(item.chunk_id for item in request.candidates)
        return RerankResult(
            candidate_ids=("wrong",) if self.invalid else ids,
            scores=(2.0,) * len(ids),
        )


async def _seed(
    session, *, source_id: str = "RERANKG4", strict: bool = True
) -> tuple[UUID, list[UUID]]:
    document_id, version_id = uuid4(), uuid4()
    session.add(LegalDocument(id=document_id, source_id=source_id, external_id=f"g4-{document_id}"))
    digest = _digest(str(version_id))
    session.add(DocumentVersion(
        id=version_id, document_id=document_id, version_number=1, raw_html="x", normalized_text="x",
        snapshot_sha256=digest, source_content_sha256=digest, normalized_text_sha256=digest,
        normalizer_version="g4", normalized_block_count=1,
    ))
    session.add(SourceProvenanceRecord(
        document_version_id=version_id, provenance_type="source_fetch", source_id=source_id,
        transport="test", operation="g4", retrieved_at=datetime.now(UTC), tls_verified=strict,
    ))
    chunks: list[UUID] = []
    for ordinal, content in enumerate(("pre" * 200, "anchor" * 200, "post" * 200)):
        chunk_id = uuid4()
        chunks.append(chunk_id)
        session.add(DocumentChunk(
            id=chunk_id, document_version_id=version_id, ordinal=ordinal, content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(str(chunk_id)),
            chunker_version="g4",
            locator={"label": "Article 1"} if ordinal == 1 else None,
        ))
        session.add(ChunkEmbedding(
            document_chunk_id=chunk_id, embedding=_vector(), embedding_model_id=SEMANTIC_PROFILE_ID,
            embedding_kind="semantic",
            dimension=384,
            embedding_input_sha256=_digest(f"v-{chunk_id}"),
        ))
    return document_id, chunks


@pytest.mark.asyncio
async def test_reranked_postgres_persists_child_scores_and_invalid_result_falls_back() -> None:
    engine = create_engine(Settings())
    sessions = create_session_factory(engine)
    document_ids: list[UUID] = []
    run_ids: list[UUID] = []
    events: list[str] = []
    diagnostics = []
    try:
        async with sessions.begin() as session:
            document_id, chunks = await _seed(session)
            document_ids.append(document_id)
        repository = PostgresRerankedSemanticRepository(
            sessions,
            ("RERANKG4",),
            _Embedder(events),
            _Reranker(events),
            observer=diagnostics.append,
        )
        result = await repository.retrieve_and_persist(RetrievalRequest(query="g4", top_k=1))
        run_ids.append(result.retrieval_run_id)
        assert events == ["embed", "rerank"]
        assert result.candidates[0].document_chunk_id == chunks[0]
        assert result.candidates[0].semantic_score is not None
        assert result.candidates[0].reranker_score == 2.0
        assert diagnostics[-1].pre_rerank_chunk_candidate_count == 3
        assert diagnostics[-1].pre_rerank_document_version_count == 1
        assert diagnostics[-1].post_collapse_document_version_count == 1
        assert diagnostics[-1].final_citation_document_version_count == 1
        assert diagnostics[-1].reranker_fallback is False
        async with sessions() as session:
            citation = await session.get(CitationRecord, result.candidates[0].citation_id)
            assert citation is not None and citation.lexical_score is None
            assert citation.document_chunk_id == chunks[0]

        fallback = PostgresRerankedSemanticRepository(
            sessions,
            ("RERANKG4",),
            _Embedder([]),
            _Reranker([], invalid=True),
            observer=diagnostics.append,
        )
        fallback_result = await fallback.retrieve_and_persist(RetrievalRequest(query="g4", top_k=1))
        run_ids.append(fallback_result.retrieval_run_id)
        assert fallback_result.candidates[0].reranker_score is None
        assert diagnostics[-1].reranker_fallback is True
        async with sessions() as session:
            run = await session.get(RetrievalRun, fallback_result.retrieval_run_id)
            assert run is not None and run.strategy_version == "v5_semantic_exact_reranker_fallback"
    finally:
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
