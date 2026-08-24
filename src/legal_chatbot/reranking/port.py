"""Provider-neutral port for the fixed offline reranker profile."""

from __future__ import annotations

from typing import Protocol

from legal_chatbot.reranking.models import RerankRequest, RerankResult


class RerankerPort(Protocol):
    """Return one finite raw logit for every supplied opaque candidate ID."""

    async def rerank(self, request: RerankRequest) -> RerankResult:
        """Rerank one bounded request without retaining its query or candidate text."""
        ...
