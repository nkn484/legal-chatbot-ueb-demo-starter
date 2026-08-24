"""Validated, bounded settings shared by legal source adapter lanes."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourceSettings(BaseSettings):
    """Source adapter settings independent from application and LLM settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    registry_path: Path = Field(
        default=Path("contracts/source-registry.json"), validation_alias="SOURCE_REGISTRY_PATH"
    )
    vbqppl_read_manifest_path: Path = Field(
        default=Path("contracts/vbqppl-read-manifest.json"),
        validation_alias="VBQPPL_READ_MANIFEST_PATH",
    )
    vbqppl_mode: Literal["rest_fallback", "soap"] = Field(
        default="rest_fallback", validation_alias="VBQPPL_MODE"
    )
    vbqppl_live_ingestion_enabled: bool = Field(
        default=False, validation_alias="VBQPPL_LIVE_INGESTION_ENABLED"
    )
    rest_connect_timeout_seconds: float = Field(
        default=10.0, ge=0.1, le=60.0, validation_alias="VBQPPL_REST_CONNECT_TIMEOUT_SECONDS"
    )
    rest_response_timeout_seconds: float = Field(
        default=30.0, ge=1.0, le=300.0, validation_alias="VBQPPL_REST_RESPONSE_TIMEOUT_SECONDS"
    )
    rest_max_response_bytes: int = Field(
        default=2_097_152,
        ge=1_024,
        le=10_485_760,
        validation_alias="VBQPPL_REST_MAX_RESPONSE_BYTES",
    )
    rest_max_attempts: int = Field(
        default=2, ge=1, le=3, validation_alias="VBQPPL_REST_MAX_ATTEMPTS"
    )
    rest_retry_max_seconds: float = Field(
        default=2.0, ge=0.0, le=60.0, validation_alias="VBQPPL_REST_RETRY_MAX_SECONDS"
    )
    soap_connect_timeout_seconds: float = Field(
        default=10.0, ge=0.1, le=60.0, validation_alias="VBQPPL_SOAP_CONNECT_TIMEOUT_SECONDS"
    )
    soap_response_timeout_seconds: float = Field(
        default=30.0, ge=1.0, le=300.0, validation_alias="VBQPPL_SOAP_RESPONSE_TIMEOUT_SECONDS"
    )
    soap_max_response_bytes: int = Field(
        default=2_097_152,
        ge=1_024,
        le=10_485_760,
        validation_alias="VBQPPL_SOAP_MAX_RESPONSE_BYTES",
    )
    soap_tls_verify: bool = Field(
        default=True,
        validation_alias=AliasChoices("VBQPPL_SOAP_TLS_VERIFY", "VBQPPL_TLS_VERIFY"),
    )
