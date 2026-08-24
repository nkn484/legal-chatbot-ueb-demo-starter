"""Pure M06 ports without provider, persistence, or document adapter dependencies."""

from typing import Protocol
from uuid import UUID

from legal_chatbot.chat.models import (
    GroundingEvidence,
    GroundingEvidenceRequest,
    ProviderAnswer,
)
from legal_chatbot.chat.planner_models import QueryPlannerResult
from legal_chatbot.retrieval.models import RetrievalRequest, RetrievalResult


class RetrievalPort(Protocol):
    """Retrieve one bounded evidence result for grounded chat orchestration."""

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Return the persisted retrieval result for the supplied bounded request."""
        ...


class GroundingEvidencePort(Protocol):
    """Load bounded grounding excerpts for a previously selected retrieval run."""

    async def load(self, request: GroundingEvidenceRequest) -> GroundingEvidence:
        """Return exact-run grounding evidence without exposing adapter concerns."""
        ...


class ProviderOutputParserPort(Protocol):
    """Parse a provider response into safe prose without performing I/O."""

    def parse(self, output: str) -> ProviderAnswer:
        """Return the parsed provider answer or raise a normalized parse failure later."""
        ...


class QueryPlannerPort(Protocol):
    """Produce one validated, provider-neutral retrieval plan from the current question."""

    async def plan(self, question: str) -> QueryPlannerResult:
        """Return no plan on every provider or validation failure; never raise content outward."""
        ...


class CanonicalAnchorResolverPort(Protocol):
    """Resolve exact user-mentioned anchors only through server-owned document data."""

    async def resolve(self, anchor_mentions: tuple[str, ...]) -> tuple[UUID, ...] | None:
        """Return unambiguous canonical document IDs, or ``None`` for any unresolved mention."""
        ...
