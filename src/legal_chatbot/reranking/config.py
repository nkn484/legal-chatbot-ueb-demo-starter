"""Validated CPU-only settings for the inactive-by-default reranking lane."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_chatbot.reranking.constants import (
    RERANKER_BATCH_SIZE,
    RERANKER_CANDIDATE_MAX,
    RERANKER_HYDRATED_TEXT_MAX_CHARS,
    RERANKER_QUERY_MAX_CHARS,
    RERANKER_THREADS,
    RERANKER_TIMEOUT_SECONDS,
)


class RerankerSettings(BaseSettings):
    """Bounded local-only settings with no runtime feature-enable switch."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
        frozen=True,
    )

    model_path: Path = Field(
        default=Path("/models/mmarco-minilm-l12-h384-int8-avx2"),
        validation_alias="RERANKER_MODEL_PATH",
    )
    batch_size: int = Field(
        default=RERANKER_BATCH_SIZE,
        ge=1,
        le=RERANKER_CANDIDATE_MAX,
        validation_alias="RERANKER_BATCH_SIZE",
    )
    threads: int = Field(default=RERANKER_THREADS, ge=1, le=8, validation_alias="RERANKER_THREADS")
    candidate_max: int = Field(
        default=RERANKER_CANDIDATE_MAX,
        ge=1,
        le=RERANKER_CANDIDATE_MAX,
        validation_alias="RERANKER_CANDIDATE_MAX",
    )
    query_max_chars: int = Field(
        default=RERANKER_QUERY_MAX_CHARS,
        ge=1,
        le=RERANKER_QUERY_MAX_CHARS,
        validation_alias="RERANKER_QUERY_MAX_CHARS",
    )
    hydrated_text_max_chars: int = Field(
        default=RERANKER_HYDRATED_TEXT_MAX_CHARS,
        ge=1,
        le=RERANKER_HYDRATED_TEXT_MAX_CHARS,
        validation_alias="RERANKER_HYDRATED_TEXT_MAX_CHARS",
    )
    timeout_seconds: float = Field(
        default=RERANKER_TIMEOUT_SECONDS,
        ge=1,
        le=30,
        validation_alias="RERANKER_TIMEOUT_SECONDS",
    )
