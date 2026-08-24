"""Pre-registered, secret-free manifest required before a scored live run."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QualityRunManifest(BaseModel):
    """Identifiers and repeatability controls, deliberately excluding prompts and credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=256)
    prompt_version: str = Field(min_length=1, max_length=128)
    strategy: str = Field(min_length=1, max_length=128)
    corpus_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampling_temperature: float = Field(ge=0, le=2)
    retry_limit: int = Field(ge=0, le=3)
    timing_protocol: str = Field(min_length=1, max_length=256)
    run_count: int = Field(ge=1, le=3)

    @field_validator("provider", "model", "prompt_version", "strategy", "timing_protocol")
    @classmethod
    def reject_secret_like_values(cls, value: str) -> str:
        if any(marker in value.casefold() for marker in ("api_key", "token=", "secret=")):
            raise ValueError("manifest field is invalid")
        return value
