"""Coverage for the deterministic local hash embedding adapter."""

import inspect
import math

import pytest
from pydantic import ValidationError

from legal_chatbot.ingestion import EmbeddingBatch, EmbeddingKind, IngestionSettings
from legal_chatbot.ingestion.embedding import LocalHashEmbeddingAdapter


@pytest.mark.asyncio
async def test_local_hash_embeddings_are_deterministic_normalized_and_distinct() -> None:
    adapter = LocalHashEmbeddingAdapter(IngestionSettings())

    first = await adapter.embed(("Điều khoản hợp đồng", "nghĩa vụ thanh toán"))
    second = await adapter.embed(("Điều khoản hợp đồng", "nghĩa vụ thanh toán"))

    assert first == second
    assert first.model_id == "local-hash-v1"
    assert first.dimension == 384
    assert first.embedding_kind is EmbeddingKind.DEMO_NON_SEMANTIC
    assert all(len(vector) == 384 for vector in first.vectors)
    assert all(math.isfinite(value) for vector in first.vectors for value in vector)
    assert all(
        math.isclose(math.fsum(value * value for value in vector), 1.0) for vector in first.vectors
    )
    assert first.vectors[0] != first.vectors[1]


@pytest.mark.asyncio
async def test_local_hash_embedding_normalizes_nfc_and_rejects_invalid_batches() -> None:
    adapter = LocalHashEmbeddingAdapter(IngestionSettings())

    decomposed = await adapter.embed(("Cafe\u0301",))
    composed = await adapter.embed(("Café",))
    assert decomposed.vectors == composed.vectors
    with pytest.raises(ValueError, match="blank"):
        await adapter.embed(("  ",))
    with pytest.raises(ValueError, match="at least one"):
        await adapter.embed(())
    with pytest.raises(ValueError, match="batch size"):
        await adapter.embed(tuple("text" for _ in range(33)))


@pytest.mark.asyncio
async def test_local_hash_embedding_uses_configured_bounded_batch_size() -> None:
    adapter = LocalHashEmbeddingAdapter(IngestionSettings(INGESTION_EMBEDDING_BATCH_SIZE=2))

    batch = await adapter.embed(("one", "two"))

    assert len(batch.vectors) == 2
    with pytest.raises(ValueError, match="batch size"):
        await adapter.embed(("one", "two", "three"))


def test_embedding_batch_rejects_bad_dimension_nonfinite_and_zero_vectors() -> None:
    unit = (1.0,) + tuple(0.0 for _ in range(383))
    with pytest.raises(ValidationError, match="dimension"):
        EmbeddingBatch(vectors=(unit,), dimension=383)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="finite"):
        EmbeddingBatch(vectors=((float("nan"),) + tuple(0.0 for _ in range(383)),))
    with pytest.raises(ValidationError, match="nonzero"):
        EmbeddingBatch(vectors=(tuple(0.0 for _ in range(384)),))


def test_embedding_implementation_does_not_use_builtin_hash() -> None:
    source = inspect.getsource(LocalHashEmbeddingAdapter)

    assert "hash(" not in source
    assert "sha256" in source
