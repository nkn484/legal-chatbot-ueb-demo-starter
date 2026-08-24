"""Bounded settings for the M06 grounded-chat contracts."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_chatbot.chat.models import (
    ANSWER_MAX_CHARS,
    CONVERSATION_CONTEXT_MAX_CHARS,
    DEFAULT_MAX_CITATIONS,
    EXCERPT_MAX_CHARS,
    MAX_CITATIONS,
    MAX_OUTPUT_TOKENS,
    PROMPT_MAX_CHARS,
    QUESTION_MAX_CHARS,
    TOTAL_EVIDENCE_MAX_CHARS,
)
from legal_chatbot.chat.planner_models import (
    PLANNER_MAX_EXPANSION_TERMS,
    PLANNER_MAX_INPUT_CHARS,
    PLANNER_MAX_OUTPUT_TOKENS,
    PLANNER_MAX_PHRASES,
)


class ChatSettings(BaseSettings):
    """Settings may reduce, but never increase, the accepted demo safety maxima."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    question_max_chars: int = Field(
        default=QUESTION_MAX_CHARS,
        ge=1,
        le=QUESTION_MAX_CHARS,
        validation_alias="CHAT_QUESTION_MAX_CHARS",
    )
    max_citations: int = Field(
        default=DEFAULT_MAX_CITATIONS,
        ge=1,
        le=MAX_CITATIONS,
        validation_alias="CHAT_MAX_CITATIONS",
    )
    excerpt_max_chars: int = Field(
        default=EXCERPT_MAX_CHARS,
        ge=1,
        le=EXCERPT_MAX_CHARS,
        validation_alias="CHAT_EXCERPT_MAX_CHARS",
    )
    total_evidence_max_chars: int = Field(
        default=TOTAL_EVIDENCE_MAX_CHARS,
        ge=1,
        le=TOTAL_EVIDENCE_MAX_CHARS,
        validation_alias="CHAT_TOTAL_EVIDENCE_MAX_CHARS",
    )
    prompt_max_chars: int = Field(
        default=PROMPT_MAX_CHARS,
        ge=1,
        le=PROMPT_MAX_CHARS,
        validation_alias="CHAT_PROMPT_MAX_CHARS",
    )
    max_output_tokens: int = Field(
        default=MAX_OUTPUT_TOKENS,
        ge=1,
        le=MAX_OUTPUT_TOKENS,
        validation_alias="CHAT_MAX_OUTPUT_TOKENS",
    )
    answer_max_chars: int = Field(
        default=ANSWER_MAX_CHARS,
        ge=1,
        le=ANSWER_MAX_CHARS,
        validation_alias="CHAT_ANSWER_MAX_CHARS",
    )
    conversation_context_max_chars: int = Field(
        default=CONVERSATION_CONTEXT_MAX_CHARS,
        ge=1,
        le=CONVERSATION_CONTEXT_MAX_CHARS,
        validation_alias="CHAT_CONVERSATION_CONTEXT_MAX_CHARS",
    )
    retrieval_planner_enabled: bool = Field(
        default=False, validation_alias="RETRIEVAL_PLANNER_ENABLED"
    )
    retrieval_planner_max_input_chars: int = Field(
        default=PLANNER_MAX_INPUT_CHARS,
        ge=1,
        le=PLANNER_MAX_INPUT_CHARS,
        validation_alias="RETRIEVAL_PLANNER_MAX_INPUT_CHARS",
    )
    retrieval_planner_max_output_tokens: int = Field(
        default=PLANNER_MAX_OUTPUT_TOKENS,
        ge=1,
        le=PLANNER_MAX_OUTPUT_TOKENS,
        validation_alias="RETRIEVAL_PLANNER_MAX_OUTPUT_TOKENS",
    )
    retrieval_planner_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=3.0,
        validation_alias="RETRIEVAL_PLANNER_TIMEOUT_SECONDS",
    )
    retrieval_planner_max_expansion_terms: int = Field(
        default=PLANNER_MAX_EXPANSION_TERMS,
        ge=1,
        le=PLANNER_MAX_EXPANSION_TERMS,
        validation_alias="RETRIEVAL_PLANNER_MAX_EXPANSION_TERMS",
    )
    retrieval_planner_max_phrases: int = Field(
        default=PLANNER_MAX_PHRASES,
        ge=1,
        le=PLANNER_MAX_PHRASES,
        validation_alias="RETRIEVAL_PLANNER_MAX_PHRASES",
    )
    retrieval_planner_max_query_count: int = Field(
        default=2,
        ge=1,
        le=2,
        validation_alias="RETRIEVAL_PLANNER_MAX_QUERY_COUNT",
    )

    @model_validator(mode="after")
    def validate_cross_field_bounds(self) -> "ChatSettings":
        if self.total_evidence_max_chars > self.max_citations * self.excerpt_max_chars:
            raise ValueError("total evidence bound exceeds citation and excerpt capacity")
        if self.prompt_max_chars < self.question_max_chars + self.total_evidence_max_chars:
            raise ValueError("prompt bound cannot contain question and evidence bounds")
        return self
