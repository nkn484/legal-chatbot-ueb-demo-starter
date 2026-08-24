"""Pure, deterministic M06 temporal and retrieval-outcome policy."""

from typing import Final
from unicodedata import normalize

from legal_chatbot.chat.models import (
    ChatOutcome,
    ChatPolicyDecision,
    ChatReasonCode,
    ChatRequest,
)
from legal_chatbot.retrieval.models import RetrievalDecision, TemporalScope

AS_OF_PHRASES: Final = ("as of", "as at", "tại thời điểm")
CURRENT_EFFECT_PHRASES: Final = (
    "đang có hiệu lực",
    "hiện nay",
    "hiện tại",
    "currently effective",
    "currently in effect",
)

NO_RESULTS_CLARIFICATION_TEXT: Final = (
    "Dạ, em chưa tìm thấy thông tin phù hợp. Thầy/cô vui lòng làm rõ câu hỏi hoặc cung cấp thêm "
    "chi tiết."
)
TEMPORAL_REFUSAL_TEXT: Final = (
    "Dạ, trong phạm vi bản demo này, em không thể trả lời về hiệu lực pháp lý tại một thời điểm "
    "cụ thể. "
    "Thầy/cô có thể hỏi về nội dung của văn bản được cung cấp."
)
GENERIC_REFUSAL_TEXT: Final = (
    "Dạ, em chưa có đủ thông tin đáng tin cậy để trả lời câu hỏi này. Thầy/cô vui lòng làm rõ "
    "câu hỏi hoặc cung cấp thêm chi tiết."
)


def effective_temporal_scope(request: ChatRequest) -> TemporalScope:
    """Return explicit temporal intent, or the bounded conservative phrase-based guard result."""

    if request.temporal_scope is not TemporalScope.NONE:
        return request.temporal_scope
    question = normalize("NFC", request.question).casefold()
    if any(phrase in question for phrase in AS_OF_PHRASES):
        return TemporalScope.AS_OF
    if any(phrase in question for phrase in CURRENT_EFFECT_PHRASES):
        return TemporalScope.CURRENT_EFFECT
    return TemporalScope.NONE


def apply_temporal_guard(request: ChatRequest) -> ChatRequest:
    """Return a copied request with only its temporal scope elevated by the pure guard."""

    return request.model_copy(update={"temporal_scope": effective_temporal_scope(request)})


def retrieval_policy_decision(decision: RetrievalDecision) -> ChatPolicyDecision:
    """Map the complete retrieval outcome table to a fail-closed chat policy route."""

    if decision is RetrievalDecision.EVIDENCE_AVAILABLE:
        return ChatPolicyDecision(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_ELIGIBLE,
            provider_allowed=True,
        )
    if decision is RetrievalDecision.NO_RESULTS:
        return ChatPolicyDecision(
            outcome=ChatOutcome.CLARIFICATION,
            reason=ChatReasonCode.NO_RESULTS,
            provider_allowed=False,
            fixed_text=NO_RESULTS_CLARIFICATION_TEXT,
        )
    if decision is RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE:
        return refusal_decision(ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE)
    if decision is RetrievalDecision.INVALID_EVIDENCE_CHAIN:
        return refusal_decision(ChatReasonCode.INVALID_EVIDENCE_CHAIN)
    raise ValueError("unsupported retrieval decision")


def refusal_decision(reason: ChatReasonCode) -> ChatPolicyDecision:
    """Create a fixed-text, no-provider refusal for an allowed failure reason."""

    if reason is ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE:
        fixed_text = TEMPORAL_REFUSAL_TEXT
    elif reason in {
        ChatReasonCode.INVALID_EVIDENCE_CHAIN,
        ChatReasonCode.RETRIEVAL_FAILURE,
        ChatReasonCode.GROUNDING_FAILURE,
        ChatReasonCode.PROVIDER_FAILURE,
        ChatReasonCode.INVALID_PROVIDER_OUTPUT,
        ChatReasonCode.CITATION_REVALIDATION_FAILURE,
    }:
        fixed_text = GENERIC_REFUSAL_TEXT
    else:
        raise ValueError("reason cannot produce a refusal")
    return ChatPolicyDecision(
        outcome=ChatOutcome.REFUSAL,
        reason=reason,
        provider_allowed=False,
        fixed_text=fixed_text,
    )
