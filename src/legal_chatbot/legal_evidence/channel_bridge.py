"""Compatibility bridge from the existing conversation seam to LegalChatApplication."""

from __future__ import annotations

from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, GroundedChatResult

from .application import LegalChatApplication, LegalChatStatus


class LegalChatGroundedChatBridge:
    """Adapt P1-P10 answer text to the stable M08 channel conversation seam.

    The legacy seam requires a GroundedChatResult and citation-backed ANSWER state.
    P1-P10 evidence is not a legacy retrieval run, so the bridge uses the safe
    non-citation route solely for channel delivery. The outbound formatter sends
    only the answer text; it never receives P1-P10 internals.
    """

    def __init__(self, application: LegalChatApplication) -> None:
        self._application = application

    async def respond(self, request) -> GroundedChatResult:
        response = await self._application.ask(
            request.question,
            correlation_id=None,
        )
        if response.status is LegalChatStatus.UNAVAILABLE:
            return GroundedChatResult(
                outcome=ChatOutcome.REFUSAL,
                reason=ChatReasonCode.RETRIEVAL_FAILURE,
                answer=response.answer_text,
            )
        return GroundedChatResult(
            outcome=ChatOutcome.REFUSAL,
            reason=ChatReasonCode.RETRIEVAL_FAILURE,
            answer=response.answer_text,
        )


__all__ = ["LegalChatGroundedChatBridge"]
