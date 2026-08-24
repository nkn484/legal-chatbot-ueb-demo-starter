"""Validated, source-neutral settings for the ingestion pipeline."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    """Bounded ingestion settings loaded from ``INGESTION_*`` environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    chunk_max_chars: int = Field(
        default=1_200,
        ge=200,
        le=8_000,
        validation_alias="INGESTION_CHUNK_MAX_CHARS",
    )
    chunk_overlap_chars: int = Field(
        default=200,
        ge=0,
        le=7_999,
        validation_alias="INGESTION_CHUNK_OVERLAP_CHARS",
    )
    html_normalizer_version: Literal["html-v1"] = Field(
        default="html-v1", validation_alias="INGESTION_HTML_NORMALIZER_VERSION"
    )
    legal_block_version: Literal["legal-block-v1"] = Field(
        default="legal-block-v1", validation_alias="INGESTION_LEGAL_BLOCK_VERSION"
    )
    embedding_model: Literal["local-hash-v1"] = Field(
        default="local-hash-v1", validation_alias="INGESTION_EMBEDDING_MODEL"
    )
    embedding_dimension: Literal[384] = Field(
        default=384, validation_alias="INGESTION_EMBEDDING_DIMENSION"
    )
    embedding_batch_size: int = Field(
        default=32, ge=1, le=256, validation_alias="INGESTION_EMBEDDING_BATCH_SIZE"
    )

    @model_validator(mode="after")
    def validate_chunk_overlap(self) -> "IngestionSettings":
        """Ensure overlap leaves a positive chunk body."""
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("INGESTION_CHUNK_OVERLAP_CHARS must be less than chunk max chars")
        return self
