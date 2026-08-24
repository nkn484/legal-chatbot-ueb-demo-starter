"""Pure ports for grounded chat and bounded conversation persistence."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from legal_chatbot.chat.models import ChatRequest, GroundedChatResult
from legal_chatbot.conversation.models import (
    ConversationRequest,
    ConversationReservation,
    ConversationReservationResult,
    ConversationStateSnapshot,
    ConversationStateUpdate,
    CreateConversationResult,
    PersistedConversationExchange,
)


class GroundedChatPort(Protocol):
    """Produce one grounded chat result from a bounded generic chat request."""

    async def respond(self, request: ChatRequest) -> GroundedChatResult:
        """Return a validated grounded result without exposing adapter concerns."""
        ...


class ConversationRepositoryPort(Protocol):
    """Persist bounded conversation state without exposing ORM or transaction details."""

    async def create_conversation(self, now: datetime) -> CreateConversationResult:
        """Create one conversation using an aware repository-clock timestamp."""
        ...

    async def reserve(
        self, request: ConversationRequest, now: datetime
    ) -> ConversationReservationResult:
        """Atomically reserve a delivery or return its bounded idempotency state."""
        ...

    async def load_snapshot(
        self, conversation_id: UUID, now: datetime
    ) -> ConversationStateSnapshot:
        """Load bounded current state using an aware repository-clock timestamp."""
        ...

    async def complete(
        self,
        reservation: ConversationReservation,
        chat: GroundedChatResult,
        state_update: ConversationStateUpdate,
        now: datetime,
    ) -> PersistedConversationExchange:
        """Atomically complete a reservation and its version-bound state update."""
        ...

    async def purge_expired(self, now: datetime, limit: int) -> int:
        """Purge at most ``limit`` expired conversations using an aware timestamp."""
        ...
