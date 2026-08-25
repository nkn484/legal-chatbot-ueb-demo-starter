"""Stage-specific optional-provider routing for legal evidence phases."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.port import LLMProviderPort


class LegalStageModelRoutingSettings(BaseSettings):
    """Keep optional P2/P4 models independent from the global chat model setting."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    p2_deterministic_first: bool = Field(
        default=True, validation_alias="LEGAL_P2_DETERMINISTIC_FIRST"
    )
    p2_model: str | None = Field(default=None, validation_alias="LEGAL_P2_MODEL")
    p2_reasoning_profile: Literal["minimal"] = Field(
        default="minimal", validation_alias="LEGAL_P2_REASONING_PROFILE"
    )
    p2_timeout_seconds: float = Field(
        default=18.0, ge=0.1, le=18.0, validation_alias="LEGAL_P2_TIMEOUT_SECONDS"
    )
    p4_model: str | None = Field(default=None, validation_alias="LEGAL_P4_MODEL")
    p4_reasoning_profile: Literal["minimal"] = Field(
        default="minimal", validation_alias="LEGAL_P4_REASONING_PROFILE"
    )
    p4_timeout_seconds: float = Field(
        default=25.0, ge=0.1, le=25.0, validation_alias="LEGAL_P4_TIMEOUT_SECONDS"
    )
    p4_batch_size: int = Field(default=3, ge=1, le=10, validation_alias="LEGAL_P4_BATCH_SIZE")
    p4_batch_concurrency: int = Field(
        default=1, ge=1, le=3, validation_alias="LEGAL_P4_BATCH_CONCURRENCY"
    )
    provider_suppression_seconds: float = Field(
        default=60.0, ge=1.0, le=300.0, validation_alias="LEGAL_PROVIDER_SUPPRESSION_SECONDS"
    )


def provider_settings_for_stage(
    provider_settings: ProviderSettings, model: str | None
) -> ProviderSettings | None:
    """Return a stage-local adapter configuration only when that stage opts into a model."""

    if model is None:
        return None
    return provider_settings.model_copy(update={"model": model})


def stage_provider(
    provider_settings: ProviderSettings,
    model: str | None,
    provider_factory: Callable[[ProviderSettings], LLMProviderPort],
) -> LLMProviderPort | None:
    """Construct an optional isolated adapter for one stage's explicitly configured model."""

    stage_settings = provider_settings_for_stage(provider_settings, model)
    return None if stage_settings is None else provider_factory(stage_settings)


@dataclass
class StageProviderCircuitBreaker:
    """Suppress known-failing optional provider work without changing legal fallback behavior."""

    suppression_seconds: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _open_until: dict[str, float] = field(default_factory=dict)

    def is_suppressed(self, stage: str) -> bool:
        return self._open_until.get(stage, 0.0) > self.clock()

    def record_failure(self, stage: str) -> None:
        self._open_until[stage] = self.clock() + self.suppression_seconds

    def record_success(self, stage: str) -> None:
        self._open_until.pop(stage, None)


__all__ = [
    "LegalStageModelRoutingSettings",
    "StageProviderCircuitBreaker",
    "provider_settings_for_stage",
    "stage_provider",
]
