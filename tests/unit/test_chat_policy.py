"""Focused deterministic policy coverage for M06 Phase 1."""

import pytest

from legal_chatbot.chat import (
    GENERIC_REFUSAL_TEXT,
    NO_RESULTS_CLARIFICATION_TEXT,
    TEMPORAL_REFUSAL_TEXT,
    ChatOutcome,
    ChatReasonCode,
    ChatRequest,
    apply_temporal_guard,
    effective_temporal_scope,
    refusal_decision,
    retrieval_policy_decision,
)
from legal_chatbot.retrieval import RetrievalDecision, TemporalScope


@pytest.mark.parametrize("phrase", ["as of", "AS AT", "tại thời điểm"])
def test_temporal_guard_detects_as_of_phrases(phrase: str) -> None:
    request = ChatRequest(question=f"Quy định {phrase} nào?")

    assert effective_temporal_scope(request) is TemporalScope.AS_OF
    assert apply_temporal_guard(request).temporal_scope is TemporalScope.AS_OF


@pytest.mark.parametrize(
    "phrase",
    ["đang có hiệu lực", "hiện nay", "hiện tại", "currently effective", "currently in effect"],
)
def test_temporal_guard_detects_current_effect_phrases(phrase: str) -> None:
    assert (
        effective_temporal_scope(ChatRequest(question=f"Văn bản {phrase}?"))
        is TemporalScope.CURRENT_EFFECT
    )


def test_explicit_non_none_scope_wins_and_as_of_wins_phrase_ties() -> None:
    tied = ChatRequest(question="as of hiện nay?")

    assert effective_temporal_scope(tied) is TemporalScope.AS_OF
    explicit = ChatRequest(question="as of", temporal_scope=TemporalScope.CURRENT_EFFECT)
    assert effective_temporal_scope(explicit) is TemporalScope.CURRENT_EFFECT
    assert apply_temporal_guard(explicit) == explicit


@pytest.mark.parametrize(
    ("retrieval_decision", "outcome", "reason", "provider_allowed", "text"),
    [
        (
            RetrievalDecision.EVIDENCE_AVAILABLE,
            ChatOutcome.ANSWER,
            ChatReasonCode.ANSWER_ELIGIBLE,
            True,
            None,
        ),
        (
            RetrievalDecision.NO_RESULTS,
            ChatOutcome.CLARIFICATION,
            ChatReasonCode.NO_RESULTS,
            False,
            NO_RESULTS_CLARIFICATION_TEXT,
        ),
        (
            RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
            ChatOutcome.REFUSAL,
            ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE,
            False,
            TEMPORAL_REFUSAL_TEXT,
        ),
        (
            RetrievalDecision.INVALID_EVIDENCE_CHAIN,
            ChatOutcome.REFUSAL,
            ChatReasonCode.INVALID_EVIDENCE_CHAIN,
            False,
            GENERIC_REFUSAL_TEXT,
        ),
    ],
)
def test_retrieval_outcome_table(
    retrieval_decision: RetrievalDecision,
    outcome: ChatOutcome,
    reason: ChatReasonCode,
    provider_allowed: bool,
    text: str | None,
) -> None:
    decision = retrieval_policy_decision(retrieval_decision)

    assert (decision.outcome, decision.reason, decision.provider_allowed, decision.fixed_text) == (
        outcome,
        reason,
        provider_allowed,
        text,
    )


def test_refusal_decision_restricts_reason_codes() -> None:
    assert refusal_decision(ChatReasonCode.PROVIDER_FAILURE).fixed_text == GENERIC_REFUSAL_TEXT
    with pytest.raises(ValueError, match="cannot"):
        refusal_decision(ChatReasonCode.NO_RESULTS)


@pytest.mark.parametrize(
    "text",
    (NO_RESULTS_CLARIFICATION_TEXT, TEMPORAL_REFUSAL_TEXT, GENERIC_REFUSAL_TEXT),
)
def test_fixed_texts_use_the_approved_vietnamese_bot_voice(text: str) -> None:
    assert text.startswith("Dạ,")
    assert "em" in text
    assert "Thầy/cô" in text
    assert "Tôi" not in text
