"""Legal source boundary that isolates retrieval from source transport details."""

from typing import Protocol

from legal_chatbot.sources.models import (
    DiscoveryCandidate,
    DiscoveryRequest,
    FetchApprovedDocumentRef,
    LegalDocumentSnapshot,
    SourceHealth,
)


class LegalSourcePort(Protocol):
    """Async contract every legal source adapter must implement."""

    async def list_documents(self) -> tuple[FetchApprovedDocumentRef, ...]:
        """List bounded fetch-approved references without source discovery I/O."""
        ...

    async def fetch_document(self, ref: FetchApprovedDocumentRef) -> LegalDocumentSnapshot:
        """Fetch one manifest-derived, transport-specific permitted document."""
        ...

    async def health_check(self) -> SourceHealth:
        """Return normalized source health without exposing transport errors."""
        ...

    async def aclose(self) -> None:
        """Release any adapter-owned async resources."""
        ...


class LegalSourceDiscoveryPort(Protocol):
    """Separate exact-number discovery boundary; unavailable to retrieval and chat."""

    async def discover_document(self, request: DiscoveryRequest) -> DiscoveryCandidate:
        """Discover one manifest-approved number and return a non-fetchable candidate."""
        ...

    async def aclose(self) -> None:
        """Release any adapter-owned async resources."""
        ...
