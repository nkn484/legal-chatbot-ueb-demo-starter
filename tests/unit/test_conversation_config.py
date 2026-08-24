"""Focused shrink-only settings coverage for M07 Phase 1."""

import pytest
from pydantic import ValidationError

from legal_chatbot.conversation import ConversationSettings


def test_conversation_settings_default_to_canonical_maxima_and_shrink_only() -> None:
    settings = ConversationSettings()

    assert settings.recent_completed_turn_limit == 4
    assert settings.rolling_summary_max_chars == 1_500
    assert settings.active_topic_max_chars == 256
    assert settings.context_max_chars == 1_000
    assert settings.reference_limit == 6
    assert settings.retained_exchange_limit == 32
    assert settings.retention_seconds == 604_800
    assert settings.processing_lease_seconds == 120
    assert (
        ConversationSettings(context_max_chars=1, recent_completed_turn_limit=1).context_max_chars
        == 1
    )
    with pytest.raises(ValidationError):
        ConversationSettings(context_max_chars=1_001)
    with pytest.raises(ValidationError):
        ConversationSettings(recent_completed_turn_limit=5)
    with pytest.raises(ValidationError):
        ConversationSettings(retained_exchange_limit=1)
    with pytest.raises(ValidationError):
        ConversationSettings(retention_seconds=59)
    with pytest.raises(ValidationError):
        ConversationSettings(processing_lease_seconds=0)


def test_conversation_settings_accept_conversation_environment_aliases(monkeypatch) -> None:
    monkeypatch.setenv("CONVERSATION_RECENT_TURNS", "3")
    monkeypatch.setenv("CONVERSATION_ROLLING_SUMMARY_MAX_CHARS", "1000")
    monkeypatch.setenv("CONVERSATION_ACTIVE_TOPIC_MAX_CHARS", "100")
    monkeypatch.setenv("CONVERSATION_CONTEXT_MAX_CHARS", "900")
    monkeypatch.setenv("CONVERSATION_REFERENCE_LIMIT", "5")
    monkeypatch.setenv("CONVERSATION_RETAINED_EXCHANGE_LIMIT", "3")
    monkeypatch.setenv("CONVERSATION_RETENTION_SECONDS", "60")
    monkeypatch.setenv("CONVERSATION_PROCESSING_LEASE_SECONDS", "1")

    settings = ConversationSettings()

    assert settings.recent_completed_turn_limit == 3
    assert settings.context_max_chars == 900
    assert settings.reference_limit == 5
    assert settings.retained_exchange_limit == 3
