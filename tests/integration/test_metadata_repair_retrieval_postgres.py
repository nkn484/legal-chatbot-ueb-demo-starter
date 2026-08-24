"""Opt-in PostgreSQL evidence for M2 metadata repair retrieval."""
# ruff: noqa: E501

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, event, func, select

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.metadata_repair_repository import (
    PostgresMetadataRepairRetrievalRepository,
)
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    CorpusCatalogEntry,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
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


def _vector(score: float) -> list[float]:
    return [score, (1.0 - score * score) ** 0.5] + [0.0] * 382


class _Embedder:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        del text
        self.events.append("embed")
        return SemanticEmbeddingBatch(vectors=(tuple(_vector(1.0)),))

    async def embed_documents(self, texts: object) -> SemanticEmbeddingBatch:
        raise AssertionError(texts)


class _Reranker:
    def __init__(
        self, events: list[str], promoted: tuple[UUID, ...] = (), *, timeout: bool = False
    ) -> None:
        self.events = events
        self.promoted = tuple(str(item) for item in promoted)
        self.timeout = timeout

    async def rerank(self, request):
        self.events.append("rerank")
        if self.timeout:
            raise TimeoutError("test timeout")
        scores = tuple(
            10.0 - self.promoted.index(item.chunk_id)
            if item.chunk_id in self.promoted
            else 0.0
            for item in request.candidates
        )
        return RerankResult.from_request(request, scores)


async def _seed_document(
    session,
    *,
    source_id: str,
    external_id: str,
    title: str,
    number: str | None,
    score: float,
    strict: bool = True,
    exact_embedding: bool = True,
    wrong_embedding: bool = False,
    document_id: UUID | None = None,
    version_number: int = 1,
) -> tuple[UUID, UUID, UUID]:
    document_id = document_id or uuid4()
    if version_number == 1:
        session.add(LegalDocument(id=document_id, source_id=source_id, external_id=external_id))
    version_id, chunk_id = uuid4(), uuid4()
    digest = _digest(str(version_id))
    content = f"evidence {external_id}"
    session.add(DocumentVersion(
        id=version_id,
        document_id=document_id,
        version_number=version_number,
        document_number=number,
        document_number_normalized=number,
        title=title,
        raw_html=content,
        normalized_text=content,
        snapshot_sha256=digest,
        source_content_sha256=digest,
        normalized_text_sha256=digest,
        normalizer_version="m2-test",
        normalized_block_count=1,
    ))
    session.add(SourceProvenanceRecord(
        document_version_id=version_id,
        provenance_type="source_fetch",
        source_id=source_id,
        transport="test",
        operation="m2-test",
        retrieved_at=datetime.now(UTC),
        tls_verified=strict,
    ))
    session.add(DocumentChunk(
        id=chunk_id,
        document_version_id=version_id,
        ordinal=0,
        content_text=content,
        start_char=0,
        end_char=len(content),
        content_sha256=_digest(str(chunk_id)),
        chunker_version="m2-test",
        locator={"label": "Article M2"},
    ))
    if exact_embedding:
        session.add(ChunkEmbedding(
            document_chunk_id=chunk_id,
            embedding=_vector(score),
            embedding_model_id=SEMANTIC_PROFILE_ID,
            embedding_kind="semantic",
            dimension=384,
            embedding_input_sha256=_digest(f"exact-{chunk_id}"),
        ))
    if wrong_embedding:
        session.add(ChunkEmbedding(
            document_chunk_id=chunk_id,
            embedding=_vector(1.0),
            embedding_model_id="wrong-semantic-profile",
            embedding_kind="semantic",
            dimension=384,
            embedding_input_sha256=_digest(f"wrong-{chunk_id}"),
        ))
    return document_id, version_id, chunk_id


@pytest.mark.asyncio
async def test_metadata_repair_postgres_seeded_merge_fallback_and_cleanup() -> None:
    engine = create_engine(Settings())
    sessions = create_session_factory(engine)
    document_ids: list[UUID] = []
    catalog_ids: list[UUID] = []
    run_ids: list[UUID] = []
    events: list[str] = []
    sql_events: list[str] = []
    diagnostics = []
    runs_before: int | None = None
    citations_before: int | None = None
    title_terms = (f"metadata{uuid4().hex}", f"title{uuid4().hex}")
    title_phrase = " ".join(title_terms)

    def record_sql(connection, cursor, statement, parameters, context, executemany) -> None:
        del connection, cursor, parameters, context, executemany
        sql_events.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        async with sessions.begin() as session:
            unique_document, unique_version, unique_chunk = await _seed_document(
                session,
                source_id="VBQPPL",
                external_id=f"m2-unique-{uuid4()}",
                title="Văn bản riêng",
                number="2725/qđ-đhkt",
                score=0.75,
            )
            document_ids.append(unique_document)
            title_document, title_version, title_chunk = await _seed_document(
                session,
                source_id="VBQPPL",
                external_id=f"m2-title-{uuid4()}",
                title=title_phrase,
                number=None,
                score=0.90,
            )
            document_ids.append(title_document)
            one_token_document, _, _ = await _seed_document(
                session,
                source_id="VBQPPL",
                external_id=f"m2-one-token-{uuid4()}",
                title=title_terms[0],
                number=None,
                score=0.10,
            )
            document_ids.append(one_token_document)
            duplicate_documents: list[UUID] = []
            duplicate_versions: list[UUID] = []
            for score in (0.30, 0.20):
                document_id, version_id, _ = await _seed_document(
                    session,
                    source_id="VBQPPL",
                    external_id=f"m2-duplicate-{uuid4()}",
                    title="Số trùng",
                    number="99/2025/qh15",
                    score=score,
                )
                document_ids.append(document_id)
                duplicate_documents.append(document_id)
                duplicate_versions.append(version_id)
            for score in (0.95, 0.85):
                document_id, _, _ = await _seed_document(
                    session,
                    source_id="VBQPPL",
                    external_id=f"m2-baseline-{uuid4()}",
                    title="Nền ngữ nghĩa",
                    number=None,
                    score=score,
                )
                document_ids.append(document_id)
            old_document, _, _ = await _seed_document(
                session,
                source_id="VBQPPL",
                external_id=f"m2-old-{uuid4()}",
                title=title_phrase,
                number=None,
                score=1.0,
            )
            _, _, _ = await _seed_document(
                session,
                source_id="VBQPPL",
                external_id="ignored-for-existing-document",
                title="Phiên bản mới không khớp",
                number=None,
                score=0.05,
                document_id=old_document,
                version_number=2,
            )
            document_ids.append(old_document)
            inactive_document, _, _ = await _seed_document(
                session,
                source_id="INACTIVE-M2",
                external_id=f"m2-inactive-{uuid4()}",
                title=title_phrase,
                number=None,
                score=1.0,
            )
            document_ids.append(inactive_document)
            untrusted_document, _, _ = await _seed_document(
                session,
                source_id="VBQPPL",
                external_id=f"m2-untrusted-{uuid4()}",
                title=title_phrase,
                number=None,
                score=1.0,
                strict=False,
            )
            document_ids.append(untrusted_document)
            wrong_profile_document, _, _ = await _seed_document(
                session,
                source_id="INACTIVE-M2",
                external_id=f"m2-wrong-profile-{uuid4()}",
                title="Khác",
                number=None,
                score=0.05,
                wrong_embedding=True,
            )
            document_ids.append(wrong_profile_document)
            await session.flush()
            for source_row in (2, 3):
                catalog_id = uuid4()
                catalog_ids.append(catalog_id)
                session.add(CorpusCatalogEntry(
                    id=catalog_id,
                    dataset_id=f"m2-{unique_document}",
                    source_id="VBQPPL",
                    workbook_name="m2.xlsx",
                    sheet_name="Sheet1",
                    source_row=source_row,
                    external_id=f"catalog-{source_row}-{unique_document}",
                    file_kind="DIRECT_FILE",
                    record_sha256=_digest(f"catalog-{source_row}-{unique_document}"),
                    processing_status="INDEXED",
                    legal_document_id=unique_document,
                    document_version_id=unique_version,
                ))

        async with sessions() as session:
            runs_before = await session.scalar(select(func.count()).select_from(RetrievalRun))
            citations_before = await session.scalar(select(func.count()).select_from(CitationRecord))
            assert runs_before is not None and citations_before is not None

        repository = PostgresMetadataRepairRetrievalRepository(
            sessions,
            ("VBQPPL",),
            _Embedder(events),
            _Reranker(events, promoted=(unique_chunk, title_chunk)),
            observer=diagnostics.append,
        )
        query = f"{title_phrase} theo 2725 / QĐ– ĐHKT và 99/2025/QH15"
        async with sessions() as session:
            identities, ambiguity = await repository._identity_versions(session, query)
            titles = await repository._title_versions(session, query)
        assert identities == (unique_version,)
        assert ambiguity == 1
        assert not set(duplicate_versions) & set(identities)
        assert titles == (title_version,)

        sql_events.clear()
        result = await repository.retrieve_and_persist(RetrievalRequest(query=query, top_k=2))
        run_ids.append(result.retrieval_run_id)
        assert events == ["embed", "rerank"]
        assert {item.document_chunk_id for item in result.candidates} >= {unique_chunk, title_chunk}
        assert all(item.semantic_score is not None and item.reranker_score is not None for item in result.candidates)
        assert diagnostics[-1].strategy_version == "v6_semantic_exact_metadata_reranked"
        assert diagnostics[-1].exact_identity_candidate_count == 1
        assert diagnostics[-1].title_candidate_count == 1
        assert diagnostics[-1].ambiguous_identity_count == 1
        assert diagnostics[-1].arm_contribution_counts["identity"] == 1
        assert diagnostics[-1].arm_contribution_counts["title"] == 1
        assert diagnostics[-1].reranker_input_count <= 16
        assert diagnostics[-1].rejection_reason_counts["IDENTITY_AMBIGUOUS"] == 1
        assert diagnostics[-1].rejection_reason_counts["METADATA_ONLY_NO_SUPPORTING_CHUNK"] == 0
        title_query_index = next(index for index, value in enumerate(sql_events) if "to_tsquery" in value)
        assert any("SET LOCAL enable_bitmapscan = on" in value for value in sql_events[:title_query_index])
        assert sum("SET LOCAL enable_bitmapscan = off" in value for value in sql_events) == 2

        async with sessions() as session:
            run = await session.get(RetrievalRun, result.retrieval_run_id)
            persisted = (await session.execute(select(CitationRecord).where(
                CitationRecord.retrieval_run_id == result.retrieval_run_id
            ))).scalars().all()
            assert run is not None and run.strategy_version == "v6_semantic_exact_metadata_reranked"
            assert {item.document_chunk_id for item in persisted} >= {unique_chunk, title_chunk}
            assert all(item.semantic_score is not None and item.reranker_score is not None for item in persisted)
            assert await session.scalar(select(func.count()).select_from(RetrievalRun)) == runs_before + 1
            assert await session.scalar(select(func.count()).select_from(CitationRecord)) == citations_before + 2

        fallback = PostgresMetadataRepairRetrievalRepository(
            sessions,
            ("VBQPPL",),
            _Embedder([]),
            _Reranker([], timeout=True),
            observer=diagnostics.append,
        )
        fallback_result = await fallback.retrieve_and_persist(RetrievalRequest(query=query, top_k=1))
        run_ids.append(fallback_result.retrieval_run_id)
        assert fallback_result.candidates[0].document_chunk_id == title_chunk
        assert fallback_result.candidates[0].reranker_score is None
        assert diagnostics[-1].reranker_fallback is True
        assert diagnostics[-1].strategy_version == "v6_semantic_exact_metadata_reranker_fallback"
        assert diagnostics[-1].rejection_reason_counts["FINAL_TOP_K_CUTOFF"] > 0
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(RetrievalRun)) == runs_before + 2
            assert await session.scalar(select(func.count()).select_from(CitationRecord)) == citations_before + 3
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)
        async with sessions.begin() as session:
            if run_ids:
                await session.execute(delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids)))
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            if catalog_ids:
                await session.execute(delete(CorpusCatalogEntry).where(CorpusCatalogEntry.id.in_(catalog_ids)))
            if document_ids:
                await session.execute(delete(LegalDocument).where(LegalDocument.id.in_(document_ids)))
        if runs_before is not None and citations_before is not None:
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(RetrievalRun)) == runs_before
                assert await session.scalar(select(func.count()).select_from(CitationRecord)) == citations_before
        await engine.dispose()
