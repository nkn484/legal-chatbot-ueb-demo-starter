"""Unit checks for document repository validation and PostgreSQL statements."""

import inspect
from datetime import UTC, datetime
from hashlib import sha256
from math import nan
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql

from legal_chatbot.documents import repository as document_repository
from legal_chatbot.documents.repository import DocumentRepository, _legal_document_insert
from legal_chatbot.ingestion.models import (
    ChunkDraft,
    EmbeddingKind,
    NormalizedBlock,
    NormalizedDocument,
)
from legal_chatbot.sources.models import LegalDocumentSnapshot, ProvenanceType, SourceProvenance


def _hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _snapshot() -> LegalDocumentSnapshot:
    html = "<p>Article 1</p>"
    return LegalDocumentSnapshot(
        source_id="VBQPPL",
        external_id="175258",
        content_html=html,
        content_sha256=_hash(html),
        provenance=SourceProvenance(
            provenance_type=ProvenanceType.SOURCE_FETCH,
            source_id="VBQPPL",
            transport="https",
            operation="fetch_document",
            retrieved_at=datetime(2026, 8, 19, tzinfo=UTC),
            tls_verified=True,
        ),
    )


def _normalized() -> NormalizedDocument:
    text = "Article 1"
    return NormalizedDocument(
        text=text,
        sha256=_hash(text),
        blocks=(NormalizedBlock(kind="article", text=text, start=0, end=len(text)),),
        normalizer_version="html-v1",
    )


def _chunk() -> ChunkDraft:
    text = "Article 1"
    return ChunkDraft(
        ordinal=0,
        start=0,
        end=len(text),
        text=text,
        content_sha256=_hash(text),
        chunker_version="legal-block-v1",
    )


def _vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


def test_document_repository_derives_normalized_number_only_for_new_version_writes() -> None:
    source = inspect.getsource(document_repository.DocumentRepository.persist)
    assert "document_number_normalized=" in source
    assert "normalize_document_number(snapshot.document_number)" in source
    assert "snapshot_sha256" in source


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vectors", "snapshot_sha256"),
    [
        ((), _hash("snapshot")),
        (((0.0,) * 383,), _hash("snapshot")),
        (((nan,) * 384,), _hash("snapshot")),
        (((0.0,) * 384,), _hash("snapshot")),
        (((0.0,) * 384,), "not-a-hash"),
    ],
)
async def test_persist_rejects_invalid_payload_before_opening_session(
    vectors: tuple[tuple[float, ...], ...], snapshot_sha256: str
) -> None:
    session_factory = Mock()
    repository = DocumentRepository(session_factory)

    with pytest.raises(ValueError):
        await repository.persist(
            _snapshot(),
            _normalized(),
            (_chunk(),),
            vectors,
            snapshot_sha256=snapshot_sha256,
            embedding_model_id="local-hash-v1",
            embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
        )

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_persist_rejects_zero_l2_vector_before_opening_session() -> None:
    session_factory = Mock()
    repository = DocumentRepository(session_factory)

    with pytest.raises(ValueError, match="nonzero L2 norm"):
        await repository.persist(
            _snapshot(),
            _normalized(),
            (_chunk(),),
            ((0.0,) * 384,),
            snapshot_sha256=_hash("snapshot"),
            embedding_model_id="local-hash-v1",
            embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
        )

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_persist_rejects_source_content_hash_mismatch_before_opening_session() -> None:
    session_factory = Mock()
    repository = DocumentRepository(session_factory)
    snapshot = _snapshot().model_copy(update={"content_sha256": _hash("other")})

    with pytest.raises(ValueError, match="source content hash"):
        await repository.persist(
            snapshot,
            _normalized(),
            (_chunk(),),
            ((0.0,) * 384,),
            snapshot_sha256=_hash("snapshot"),
            embedding_model_id="local-hash-v1",
            embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
        )

    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_persist_rejects_normalized_text_hash_mismatch_before_opening_session() -> None:
    session_factory = Mock()
    repository = DocumentRepository(session_factory)
    normalized = _normalized().model_copy(update={"sha256": _hash("other")})

    with pytest.raises(ValueError, match="normalized text hash"):
        await repository.persist(
            _snapshot(),
            normalized,
            (_chunk(),),
            ((0.0,) * 384,),
            snapshot_sha256=_hash("snapshot"),
            embedding_model_id="local-hash-v1",
            embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
        )

    session_factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunks", "error"),
    [
        ((_chunk().model_copy(update={"ordinal": 1}),), "chunk ordinals"),
        ((_chunk().model_copy(update={"end": len(_normalized().text) + 1}),), "bounds"),
        ((_chunk().model_copy(update={"start": 1, "end": len(_normalized().text)}),), "match"),
    ],
)
async def test_persist_rejects_invalid_chunk_alignment_before_opening_session(
    chunks: tuple[ChunkDraft, ...], error: str
) -> None:
    session_factory = Mock()
    repository = DocumentRepository(session_factory)

    with pytest.raises(ValueError, match=error):
        await repository.persist(
            _snapshot(),
            _normalized(),
            chunks,
            (_vector(),),
            snapshot_sha256=_hash("snapshot"),
            embedding_model_id="local-hash-v1",
            embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
        )

    session_factory.assert_not_called()


def test_repository_exposes_append_only_api_without_mutation_methods() -> None:
    public_methods = {
        name
        for name in DocumentRepository.__dict__
        if not name.startswith("_") and name != "__module__"
    }

    assert public_methods == {"find_existing", "persist"}
    assert "application-role and repository discipline" in (DocumentRepository.__doc__ or "")
    assert "no database triggers" in (DocumentRepository.__doc__ or "")


def test_legal_document_insert_compiles_to_postgresql_conflict_safe_sql() -> None:
    statement = _legal_document_insert("VBQPPL", "175258")
    compiled = str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "ON CONFLICT (source_id, external_id) DO NOTHING" in compiled
