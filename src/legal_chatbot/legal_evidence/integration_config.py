"""Feature-gated runtime configuration for the existing channel integration."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LegalChatIntegrationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    enabled: bool = Field(default=False, validation_alias="LEGAL_CHAT_PIPELINE_ENABLED")
    processing_status_enabled: bool = Field(
        default=True, validation_alias="LEGAL_CHAT_PROCESSING_STATUS_ENABLED"
    )
    eta_enabled: bool = Field(default=True, validation_alias="LEGAL_CHAT_ETA_ENABLED")
    initial_eta_min_seconds: int = Field(
        default=30, ge=1, le=300, validation_alias="LEGAL_CHAT_INITIAL_ETA_MIN_SECONDS"
    )
    initial_eta_max_seconds: int = Field(
        default=60, ge=1, le=300, validation_alias="LEGAL_CHAT_INITIAL_ETA_MAX_SECONDS"
    )


__all__ = ["LegalChatIntegrationSettings"]
