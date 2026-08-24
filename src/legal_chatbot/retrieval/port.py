"""Pure persistence and citation-resolution ports for retrieval orchestration."""

from typing import Protocol
from uuid import UUID

from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
)


class RetrievalRepositoryPort(Protocol):
    """Persistence boundary implemented later by a retrieval infrastructure adapter."""

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        """Return a persisted, lexically retrieved evidence result."""
        ...

    async def persist_zero_evidence_run(
        self,
        request: RetrievalRequest,
        decision: RetrievalDecision,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        """Persist a no-evidence run without issuing a retrieval query."""
        ...


class CitationResolverPort(Protocol):
    """Resolve one citation only when it belongs to the expected retrieval run."""

    async def resolve(self, citation_id: UUID, expected_retrieval_run_id: UUID) -> ResolvedCitation:
        """Return exact citation provenance without returning chunk text."""
        ...
