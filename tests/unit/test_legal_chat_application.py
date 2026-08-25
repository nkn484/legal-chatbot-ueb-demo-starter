from types import SimpleNamespace

import pytest

from legal_chatbot.chat.models import ChatOutcome, ChatReasonCode, ChatRequest
from legal_chatbot.legal_evidence.application import (
    LegalChatApplication,
    LegalChatStatus,
)
from legal_chatbot.legal_evidence.channel_bridge import LegalChatGroundedChatBridge
from legal_chatbot.legal_evidence.models import CoverageState


class _Investigator:
    async def investigate(self, question):
        return SimpleNamespace(
            answer_draft=SimpleNamespace(text="P10 answer text"),
            coverage_matrix=SimpleNamespace(
                entries=(SimpleNamespace(state=CoverageState.SUPPORTED),)
            ),
            limitations=(),
        )


class _UnavailableInvestigator:
    async def investigate(self, question):
        raise RuntimeError


@pytest.mark.asyncio
async def test_application_exposes_one_channel_neutral_ask_entrypoint() -> None:
    application = LegalChatApplication(_Investigator())
    status = application.processing_status("delivery-1")
    response = await application.ask(
        "private legal question", correlation_id="delivery-1"
    )

    assert response.status is LegalChatStatus.ANSWER
    assert response.answer_text == "P10 answer text"
    assert response.correlation_id == "delivery-1"
    assert status.correlation_id == "delivery-1"
    assert status.estimated_wait_min_seconds < status.estimated_wait_max_seconds


@pytest.mark.asyncio
async def test_channel_bridge_returns_only_safe_p10_text_and_unavailable_refusal() -> None:
    request = ChatRequest(question="private legal question")
    answered = await LegalChatGroundedChatBridge(LegalChatApplication(_Investigator())).respond(
        request
    )
    unavailable = await LegalChatGroundedChatBridge(
        LegalChatApplication(_UnavailableInvestigator())
    ).respond(request)

    assert answered.answer == "P10 answer text"
    assert answered.outcome is ChatOutcome.REFUSAL
    assert answered.reason is ChatReasonCode.RETRIEVAL_FAILURE
    assert unavailable.outcome is ChatOutcome.REFUSAL
    assert unavailable.reason is ChatReasonCode.RETRIEVAL_FAILURE
