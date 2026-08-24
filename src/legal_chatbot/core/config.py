"""Validated runtime configuration."""

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

_DATABASE_URL_ERROR = "DATABASE_URL must be a complete postgresql+asyncpg URL"


class Settings(BaseSettings):
    """Runtime settings loaded from environment without exposing credentials."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    database_url: SecretStr = Field(validation_alias="DATABASE_URL", repr=False)
    app_env: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    host: str = Field(
        default="127.0.0.1", min_length=1, max_length=255, validation_alias="APP_HOST"
    )
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="APP_PORT")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", validation_alias="LOG_LEVEL"
    )
    database_connect_timeout_seconds: float = Field(
        default=5.0, ge=1.0, le=30.0, validation_alias="DATABASE_CONNECT_TIMEOUT_SECONDS"
    )
    database_readiness_timeout_seconds: float = Field(
        default=3.0, ge=1.0, le=30.0, validation_alias="DATABASE_READINESS_TIMEOUT_SECONDS"
    )

    @field_validator("database_url")
    @classmethod
    def validate_asyncpg_database_url(cls, value: SecretStr) -> SecretStr:
        """Accept only a complete SQLAlchemy PostgreSQL asyncpg connection URL."""
        try:
            database_url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError(_DATABASE_URL_ERROR) from None

        if (
            database_url.drivername != "postgresql+asyncpg"
            or not database_url.host
            or not database_url.database
            or not database_url.username
            or not database_url.password
        ):
            raise ValueError(_DATABASE_URL_ERROR)
        return value
