"""Safe, normalized errors for the channel-neutral conversation boundary."""

from enum import StrEnum


class ConversationErrorCode(StrEnum):
    """Stable failure categories containing no user or provider content."""

    NOT_FOUND = "NOT_FOUND"
    EXPIRED = "EXPIRED"
    IN_PROGRESS = "IN_PROGRESS"
    BUSY = "BUSY"
    CONFLICT = "CONFLICT"
    DELIVERY_INVALID = "DELIVERY_INVALID"
    STATE_INVALID = "STATE_INVALID"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"


class ConversationError(Exception):
    """A code-only exception safe for callers and structured logs."""

    def __init__(self, code: ConversationErrorCode) -> None:
        self.code = code
        super().__init__(code.value)

    def __str__(self) -> str:
        return self.code.value
