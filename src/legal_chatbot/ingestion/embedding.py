"""Local deterministic demo embeddings behind a source-neutral port."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from hashlib import sha256
from math import fsum, sqrt
from typing import Protocol

from legal_chatbot.ingestion.config import IngestionSettings
from legal_chatbot.ingestion.models import EmbeddingBatch, EmbeddingKind

_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


class EmbeddingPort(Protocol):
    """Boundary for producing a bounded batch of text embeddings."""

    async def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed up to the configured number of nonblank texts."""
        ...


class LocalHashEmbeddingAdapter:
    """A deterministic 384-dimensional signed feature-hashing demo adapter."""

    def __init__(self, settings: IngestionSettings) -> None:
        self._settings = settings

    async def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Create one normalized local-hash vector for each supplied text."""
        if isinstance(texts, str) or not texts:
            raise ValueError("texts must contain at least one text")
        if len(texts) > self._settings.embedding_batch_size:
            raise ValueError("texts must not exceed the configured embedding batch size")

        vectors = tuple(self._embed_text(text) for text in texts)
        return EmbeddingBatch(
            model_id=self._settings.embedding_model,
            dimension=self._settings.embedding_dimension,
            embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
            vectors=vectors,
        )

    def _embed_text(self, text: str) -> tuple[float, ...]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("embedding text must not be blank")
        normalized = unicodedata.normalize("NFC", text).lower()
        tokens = _TOKEN_PATTERN.findall(normalized)
        if not tokens:
            raise ValueError("embedding text must contain at least one token")

        values = [0.0] * self._settings.embedding_dimension
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            bucket = (
                int.from_bytes(digest[:8], byteorder="big") % self._settings.embedding_dimension
            )
            sign = 1.0 if digest[8] & 1 else -1.0
            values[bucket] += sign

        norm = sqrt(fsum(value * value for value in values))
        if norm == 0:
            raise RuntimeError("signed hashing unexpectedly produced a zero vector")
        return tuple(value / norm for value in values)
