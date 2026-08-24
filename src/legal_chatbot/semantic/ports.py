"""Provider-neutral port for the fixed semantic profile."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from legal_chatbot.semantic.models import SemanticEmbeddingBatch


class SemanticEmbeddingPort(Protocol):
    """Embed bounded document passages or exactly one query."""

    async def embed_documents(self, texts: Sequence[str]) -> SemanticEmbeddingBatch:
        """Return E5 passage embeddings for supplied document text."""
        ...

    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        """Return one E5 query embedding for supplied query text."""
        ...
