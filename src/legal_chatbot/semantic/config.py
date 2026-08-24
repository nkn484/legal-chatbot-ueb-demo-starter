"""Validated settings for the isolated offline semantic embedding lane."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class SemanticSettings(BaseSettings):
    """Bounded CPU-only E5 settings; no runtime retrieval switch is exposed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    model_path: Path = Field(
        default=Path("/models/multilingual-e5-small"), validation_alias="SEMANTIC_MODEL_PATH"
    )
    batch_size: int = Field(default=16, ge=1, le=64, validation_alias="SEMANTIC_BATCH_SIZE")
    threads: int = Field(default=2, ge=1, le=8, validation_alias="SEMANTIC_THREADS")
    backfill_batch_size: int = Field(
        default=16, ge=1, le=64, validation_alias="SEMANTIC_BACKFILL_BATCH_SIZE"
    )
    backfill_source_ids: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("VBQPPL", "VNU", "UEB"), validation_alias="SEMANTIC_BACKFILL_SOURCE_IDS"
    )

    @field_validator("backfill_source_ids", mode="before")
    @classmethod
    def parse_source_ids(cls, value: object) -> tuple[str, ...] | object:
        """Permit an env-friendly CSV while retaining an immutable bounded tuple."""

        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("backfill_source_ids")
    @classmethod
    def validate_source_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if (
            not 1 <= len(value) <= 3
            or len(set(value)) != len(value)
            or any(source not in {"VBQPPL", "VNU", "UEB"} for source in value)
        ):
            raise ValueError(
                "SEMANTIC_BACKFILL_SOURCE_IDS must be a unique tuple from the registry"
            )
        return value
