"""Shrink-only settings for bounded conversation orchestration."""

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_chatbot.chat.models import (
    CONVERSATION_CONTEXT_MAX_CHARS,
    CONVERSATION_CONTEXT_TURN_LIMIT,
)
from legal_chatbot.conversation.models import (
    ACTIVE_TOPIC_MAX_CHARS,
    PROCESSING_LEASE_SECONDS,
    REFERENCE_LIMIT_PER_KIND,
    RETAINED_EXCHANGE_LIMIT,
    RETENTION_SECONDS,
    ROLLING_SUMMARY_MAX_CHARS,
)


class ConversationSettings(BaseSettings):
    """Settings may lower, but never raise, channel-neutral safety maxima."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    recent_completed_turn_limit: int = Field(
        default=CONVERSATION_CONTEXT_TURN_LIMIT,
        ge=1,
        le=CONVERSATION_CONTEXT_TURN_LIMIT,
        validation_alias=AliasChoices(
            "CONVERSATION_RECENT_COMPLETED_TURN_LIMIT", "CONVERSATION_RECENT_TURNS"
        ),
    )
    rolling_summary_max_chars: int = Field(
        default=ROLLING_SUMMARY_MAX_CHARS,
        ge=1,
        le=ROLLING_SUMMARY_MAX_CHARS,
        validation_alias="CONVERSATION_ROLLING_SUMMARY_MAX_CHARS",
    )
    active_topic_max_chars: int = Field(
        default=ACTIVE_TOPIC_MAX_CHARS,
        ge=1,
        le=ACTIVE_TOPIC_MAX_CHARS,
        validation_alias="CONVERSATION_ACTIVE_TOPIC_MAX_CHARS",
    )
    context_max_chars: int = Field(
        default=CONVERSATION_CONTEXT_MAX_CHARS,
        ge=1,
        le=CONVERSATION_CONTEXT_MAX_CHARS,
        validation_alias="CONVERSATION_CONTEXT_MAX_CHARS",
    )
    reference_limit: int = Field(
        default=REFERENCE_LIMIT_PER_KIND,
        ge=1,
        le=REFERENCE_LIMIT_PER_KIND,
        validation_alias="CONVERSATION_REFERENCE_LIMIT",
    )
    retained_exchange_limit: int = Field(
        default=RETAINED_EXCHANGE_LIMIT,
        ge=2,
        le=RETAINED_EXCHANGE_LIMIT,
        validation_alias="CONVERSATION_RETAINED_EXCHANGE_LIMIT",
    )
    retention_seconds: int = Field(
        default=RETENTION_SECONDS,
        ge=60,
        le=RETENTION_SECONDS,
        validation_alias="CONVERSATION_RETENTION_SECONDS",
    )
    processing_lease_seconds: int = Field(
        default=PROCESSING_LEASE_SECONDS,
        ge=1,
        le=PROCESSING_LEASE_SECONDS,
        validation_alias="CONVERSATION_PROCESSING_LEASE_SECONDS",
    )

    @model_validator(mode="after")
    def validate_chat_compatibility(self) -> "ConversationSettings":
        if self.context_max_chars > CONVERSATION_CONTEXT_MAX_CHARS:
            raise ValueError("conversation context bound exceeds the chat context bound")
        if self.recent_completed_turn_limit > CONVERSATION_CONTEXT_TURN_LIMIT:
            raise ValueError("conversation turn bound exceeds the chat turn bound")
        return self
