"""Opt-in PostgreSQL coverage for the Prompt-01 read-only diagnostic."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.diagnostics.fulltext_root_cause import (
    ControlledCase,
    FulltextRootCauseEvaluator,
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
    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        del text
        return SemanticEmbeddingBatch(vectors=(tuple(_vector()),))


async def _seed_document(
    session,
    *,
    number: str,
    title: str,
    content: str,
    strict: bool = True,
    exact_profile: bool = True,
    old_version: bool = False,
) -> tuple[UUID, UUID, UUID]:
    document_id = uuid4()
    session.add(
        LegalDocument(id=document_id, source_id="VBQPPL", external_id=f"diag-{document_id}")
    )
    await session.flush()
    versions = (1, 2) if old_version else (1,)
    latest_id = uuid4()
    latest_chunk_id = uuid4()
    version_rows: list[tuple[int, UUID, UUID]] = []
    for version_number in versions:
        version_id = latest_id if version_number == max(versions) else uuid4()
        chunk_id = latest_chunk_id if version_number == max(versions) else uuid4()
        version_rows.append((version_number, version_id, chunk_id))
        digest = _digest(f"version-{version_id}")
        session.add(
            DocumentVersion(
                id=version_id,
                document_id=document_id,
                version_number=version_number,
                document_number=number,
                title=title,
                raw_html="private",
                normalized_text="private",
                snapshot_sha256=digest,
                source_content_sha256=digest,
                normalized_text_sha256=digest,
                normalizer_version="diagnostic-test",
                normalized_block_count=1,
            )
        )
    await session.flush()
    for _version_number, version_id, chunk_id in version_rows:
        session.add(
            DocumentChunk(
                id=chunk_id,
                document_version_id=version_id,
                ordinal=0,
                content_text=content,
                start_char=0,
                end_char=len(content),
                content_sha256=_digest(f"chunk-{chunk_id}"),
                chunker_version="diagnostic-test",
            )
        )
        session.add(
            SourceProvenanceRecord(
                document_version_id=version_id,
                provenance_type="source_fetch",
                source_id="VBQPPL",
                transport="test",
                operation="diagnostic",
                retrieved_at=datetime.now(UTC),
                tls_verified=strict,
            )
        )
    await session.flush()
    for version_number, _, chunk_id in version_rows:
        if exact_profile and strict and version_number == max(versions):
            session.add(
                ChunkEmbedding(
                    document_chunk_id=chunk_id,
                    embedding=_vector(),
                    embedding_model_id=SEMANTIC_PROFILE_ID,
                    embedding_kind="semantic",
                    dimension=384,
                    embedding_input_sha256=_digest(f"embedding-{chunk_id}"),
                )
            )
        elif not exact_profile and strict and version_number == max(versions):
            session.add(
                ChunkEmbedding(
                    document_chunk_id=chunk_id,
                    embedding=_vector(),
                    embedding_model_id="wrong-profile",
                    embedding_kind="semantic",
                    dimension=384,
                    embedding_input_sha256=_digest(f"wrong-{chunk_id}"),
                )
            )
    await session.flush()
    return document_id, latest_id, latest_chunk_id


async def _catalog(
    session, document_id: UUID, version_id: UUID, number: str, title: str, source_row: int
) -> UUID:
    entry_id = uuid4()
    session.add(
        CorpusCatalogEntry(
            id=entry_id,
            dataset_id="diagnostic-test",
            source_id="VBQPPL",
            workbook_name="controlled.xlsx",
            sheet_name="catalog",
            source_row=source_row,
            external_id=str(document_id),
            document_number=number,
            title=title,
            file_kind="DIRECT_FILE",
            record_sha256=_digest(f"catalog-{entry_id}"),
            processing_status="INDEXED",
            legal_document_id=document_id,
            document_version_id=version_id,
        )
    )
    await session.flush()
    return entry_id


@pytest.mark.asyncio
async def test_diagnostic_uses_latest_exact_rows_and_writes_nothing() -> None:
    engine = create_engine(Settings())  # type: ignore[call-arg]
    sessions = create_session_factory(engine)
    document_ids: list[UUID] = []
    catalog_ids: list[UUID] = []
    try:
        async with sessions.begin() as session:
            main_document, main_version, _ = await _seed_document(
                session,
                number="2725/QĐ-ĐHKT",
                title="main document",
                content="probe evidence",
                old_version=True,
            )
            document_ids.append(main_document)
            catalog_ids.append(
                await _catalog(
                    session, main_document, main_version, "2725 /QĐ- ĐHKT", "main document", 2
                )
            )
            catalog_ids.append(
                await _catalog(
                    session, main_document, main_version, "2725/QĐ-ĐHKT", "main document", 4
                )
            )
            title_document, title_version, _ = await _seed_document(
                session,
                number="TITLE/01",
                title="qzvxytitlemarker quy định quy chế hướng dẫn",
                content="unrelated body",
                exact_profile=False,
            )
            document_ids.append(title_document)
            catalog_ids.append(
                await _catalog(
                    session,
                    title_document,
                    title_version,
                    "TITLE/01",
                    "qzvxytitlemarker quy định quy chế hướng dẫn",
                    3,
                )
            )
            untrusted, _, _ = await _seed_document(
                session,
                number="UNTRUSTED/01",
                title="probe untrusted",
                content="probe evidence",
                strict=False,
            )
            wrong_profile, _, _ = await _seed_document(
                session,
                number="WRONG/01",
                title="probe wrong profile",
                content="probe evidence",
                exact_profile=False,
            )
            document_ids.extend((untrusted, wrong_profile))
        async with sessions() as session:
            before = (
                int((await session.scalar(select(func.count(RetrievalRun.id)))) or 0),
                int((await session.scalar(select(func.count(CitationRecord.id)))) or 0),
            )
        evaluator = FulltextRootCauseEvaluator(sessions, _Embedder(), None)
        result = await evaluator.evaluate(
            (
                ControlledCase(
                    "Q01",
                    "probe",
                    "qzvxytitlemarker",
                    ("2725/QĐ-ĐHKT", "TITLE/01"),
                ),
            )
        )
        documents = result["cases"][0]["documents"]
        main, title_only = documents
        assert main["raw_normalization_mismatch"] is True
        assert main["duplicates"] is True
        assert main["is_indexed"] is True
        assert main["d_exact_control_rank"] is not None
        assert main["merged_top50_rank"] is not None
        assert title_only["title_metadata_rank"] is not None
        assert title_only["lane_ranks"]["A_semantic"] is None
        assert title_only["d_exact_control_rank"] is not None
        assert title_only["merged_top50_rank"] is None
        assert len(result["cases"][0]["trace"]["D_EXACT_NUMBER_CONTROL_candidates"]) == 2
        for document in documents:
            if document["merged_top50_rank"] is not None:
                assert any(rank is not None for rank in document["lane_ranks"].values())
        semantic_numbers = {
            row["document_number"]
            for row in result["cases"][0]["trace"]["semantic_candidates"][
                "A_PRODUCTION_EQUIVALENT_NATURAL_QUESTION"
            ]
        }
        assert "2725/QĐ-ĐHKT" in semantic_numbers
        assert "UNTRUSTED/01" not in semantic_numbers
        assert "WRONG/01" not in semantic_numbers
        async with sessions() as session:
            after = (
                int((await session.scalar(select(func.count(RetrievalRun.id)))) or 0),
                int((await session.scalar(select(func.count(CitationRecord.id)))) or 0),
            )
        assert after == before
    finally:
        async with sessions.begin() as session:
            if catalog_ids:
                await session.execute(
                    delete(CorpusCatalogEntry).where(CorpusCatalogEntry.id.in_(catalog_ids))
                )
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()
