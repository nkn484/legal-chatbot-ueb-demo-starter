"""Explicitly opt-in live VBQPPL ingestion smoke test; never enabled by default."""

from __future__ import annotations

import json
import os

import pytest

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.ingestion import (
    DeterministicChunker,
    HTMLNormalizer,
    IngestionService,
    IngestionSettings,
    LocalHashEmbeddingAdapter,
)
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.registry import create_source, load_registry

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INGESTION_LIVE") != "1",
        reason="set RUN_INGESTION_LIVE=1 to permit a live VBQPPL read",
    ),
]


@pytest.mark.asyncio
async def test_live_vbqppl_ingestion_is_idempotent_and_output_is_sanitized() -> None:
    """Fetch only the registry's read-only reference and retain no live document content."""
    from legal_chatbot.documents.repository import DocumentRepository

    settings = Settings()
    source_settings = SourceSettings(VBQPPL_MODE="rest_fallback")
    ingestion_settings = IngestionSettings()
    registry = load_registry(source_settings.registry_path)
    source = create_source("VBQPPL", source_settings, registry)
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        service = IngestionService(
            DocumentRepository(session_factory),
            HTMLNormalizer(),
            DeterministicChunker(ingestion_settings),
            LocalHashEmbeddingAdapter(ingestion_settings),
            ingestion_settings,
        )
        refs = await source.list_documents()
        assert len(refs) == 1
        snapshot = await source.fetch_document(refs[0])
        assert snapshot.source_id == refs[0].source_id == "VBQPPL"
        assert snapshot.external_id == refs[0].external_id
        first = await service.ingest_snapshot(snapshot)
        second = await service.ingest_snapshot(snapshot)
        payload = {
            "first_outcome": first.outcome.value,
            "second_outcome": second.outcome.value,
            "same_document_id": first.document_id == second.document_id,
            "same_document_version_id": first.document_version_id == second.document_version_id,
            "first_chunk_count": first.chunk_count,
            "second_chunk_count": second.chunk_count,
            "first_embedding_count": first.embedding_count,
            "second_embedding_count": second.embedding_count,
            "hash_present": bool(snapshot.content_sha256),
            "first_semantic_ready": first.semantic_ready,
            "second_semantic_ready": second.semantic_ready,
        }
        serialized = json.dumps(payload, sort_keys=True)

        assert first.outcome.value in {"created", "unchanged"}
        assert second.outcome.value == "unchanged"
        assert first.document_id == second.document_id
        assert first.document_version_id == second.document_version_id
        assert first.version_number == second.version_number
        assert first.chunk_count == first.embedding_count > 0
        assert second.chunk_count == second.embedding_count > 0
        assert first.chunk_count == second.chunk_count
        assert first.embedding_count == second.embedding_count
        assert payload["hash_present"] is True
        assert first.semantic_ready is False
        assert second.semantic_ready is False
        assert snapshot.content_html not in serialized
        print(serialized)
    finally:
        await source.aclose()
        await engine.dispose()
