"""Focused bounded-settings coverage for M06 Phase 1."""

import pytest
from pydantic import ValidationError

from legal_chatbot.chat import ChatSettings


def test_chat_settings_default_to_demo_maxima_and_allow_only_shrinking() -> None:
    settings = ChatSettings()

    assert settings.question_max_chars == 4_000
    assert settings.max_citations == 3
    assert settings.excerpt_max_chars == 2_000
    assert settings.total_evidence_max_chars == 6_000
    assert settings.prompt_max_chars == 12_000
    assert settings.max_output_tokens == 384
    assert settings.answer_max_chars == 4_000
    assert settings.conversation_context_max_chars == 1_000
    assert settings.retrieval_planner_enabled is False
    assert settings.retrieval_planner_max_input_chars == 900
    assert settings.retrieval_planner_max_output_tokens == 96
    assert settings.retrieval_planner_timeout_seconds == 3
    assert settings.retrieval_planner_max_expansion_terms == 4
    assert settings.retrieval_planner_max_phrases == 2
    assert settings.retrieval_planner_max_query_count == 2
    assert ChatSettings(question_max_chars=1, max_output_tokens=1).question_max_chars == 1
    with pytest.raises(ValidationError):
        ChatSettings(max_citations=7)
    with pytest.raises(ValidationError):
        ChatSettings(answer_max_chars=4_001)
    assert ChatSettings(conversation_context_max_chars=1).conversation_context_max_chars == 1
    with pytest.raises(ValidationError):
        ChatSettings(conversation_context_max_chars=1_001)
    with pytest.raises(ValidationError):
        ChatSettings(retrieval_planner_max_input_chars=901)
    with pytest.raises(ValidationError):
        ChatSettings(retrieval_planner_max_query_count=3)


def test_chat_settings_enforce_evidence_capacity_and_prompt_capacity() -> None:
    with pytest.raises(ValidationError, match="total evidence"):
        ChatSettings(max_citations=1, excerpt_max_chars=2_000, total_evidence_max_chars=2_001)
    with pytest.raises(ValidationError, match="prompt bound"):
        ChatSettings(
            question_max_chars=4_000, total_evidence_max_chars=6_000, prompt_max_chars=9_999
        )
    settings = ChatSettings(
        question_max_chars=1_000,
        max_citations=2,
        excerpt_max_chars=2_000,
        total_evidence_max_chars=4_000,
        prompt_max_chars=5_000,
    )
    assert settings.prompt_max_chars == 5_000
