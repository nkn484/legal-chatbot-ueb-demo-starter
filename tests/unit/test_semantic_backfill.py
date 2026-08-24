"""Unit contracts for idempotent, content-free offline semantic backfill."""

from __future__ import annotations

from uuid import uuid4

import pytest

from legal_chatbot.documents.semantic_embedding_repository import (
    PendingSemanticChunk,
    SemanticEmbeddingRepository,
    SemanticEmbeddingWrite,
    semantic_embedding_input_sha256,
)
from legal_chatbot.semantic.backfill import SemanticBackfillService
from legal_chatbot.semantic.constants import PASSAGE_PREFIX, SEMANTIC_PROFILE_ID
from legal_chatbot.semantic.models import SemanticEmbeddingBatch


def _unit_vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


def test_semantic_backfill_repository_statement_value_is_semantic_and_prefixed_hash() -> None:
    chunk_id = uuid4()
    value = SemanticEmbeddingRepository._validated_insert_value(
        SemanticEmbeddingWrite(
            chunk_id=chunk_id,
            content_text="trusted chunk",
            vector=_unit_vector(),
        )
    )
    assert value["embedding_model_id"] == SEMANTIC_PROFILE_ID
    assert value["embedding_kind"] == "semantic"
    assert value["dimension"] == 384
    assert value["embedding_input_sha256"] == semantic_embedding_input_sha256("trusted chunk")
    assert value["embedding_input_sha256"] != semantic_embedding_input_sha256(
        PASSAGE_PREFIX + "trusted chunk"
    )


@pytest.mark.asyncio
async def test_semantic_backfill_is_idempotent_and_embeds_outside_repository_insert() -> None:
    chunk = PendingSemanticChunk(uuid4(), "VBQPPL", "eligible evidence")

    class FakeRepository:
        def __init__(self) -> None:
            self.fetched = False
            self.inserted: list[SemanticEmbeddingWrite] = []

        async def fetch_missing_batch(self, *, after_chunk_id, batch_size):
            del after_chunk_id, batch_size
            if self.fetched:
                return ()
            self.fetched = True
            return (chunk,)

        async def insert_missing(self, rows):
            self.inserted.extend(rows)
            return len(rows)

        async def coverage(self):
            return {"VBQPPL": (1, 1)}

    class FakeEmbedder:
        async def embed_documents(self, texts):
            assert texts == ("eligible evidence",)
            return SemanticEmbeddingBatch(vectors=(_unit_vector(),))

        async def embed_query(self, text):
            raise AssertionError(text)

    repository = FakeRepository()
    result = await SemanticBackfillService(repository, FakeEmbedder(), batch_size=16).run()
    assert result.inserted == 1
    assert len(repository.inserted) == 1
    assert repository.inserted[0].content_text == "eligible evidence"
