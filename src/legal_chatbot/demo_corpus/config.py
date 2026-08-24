"""Bounded settings for the approved manual snapshot corpus."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DemoCorpusSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
        populate_by_name=True,
    )

    enabled: bool = Field(default=False, validation_alias="DEMO_CORPUS_ENABLED")
    data_path: Path = Field(default=Path("demo_data"), validation_alias="DEMO_CORPUS_DATA_PATH")
    dataset_id: str = Field(
        default="demo-data-v1",
        min_length=1,
        max_length=128,
        validation_alias="DEMO_CORPUS_DATASET_ID",
    )
    retrieval_source_ids_csv: str = Field(
        default="VBQPPL,VNU,UEB",
        validation_alias="DEMO_CORPUS_RETRIEVAL_SOURCE_IDS",
    )
    connect_timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        validation_alias="DEMO_CORPUS_CONNECT_TIMEOUT_SECONDS",
    )
    response_timeout_seconds: float = Field(
        default=90.0,
        ge=1.0,
        le=300.0,
        validation_alias="DEMO_CORPUS_RESPONSE_TIMEOUT_SECONDS",
    )
    processing_timeout_seconds: float = Field(
        default=120.0,
        ge=5.0,
        le=900.0,
        validation_alias="DEMO_CORPUS_PROCESSING_TIMEOUT_SECONDS",
    )
    max_response_bytes: int = Field(
        default=67_108_864,
        ge=1_024,
        le=134_217_728,
        validation_alias="DEMO_CORPUS_MAX_RESPONSE_BYTES",
    )
    ocr_enabled: bool = Field(default=False, validation_alias="DEMO_CORPUS_OCR_ENABLED")
    ocr_executable: str = Field(
        default="tesseract",
        min_length=1,
        max_length=512,
        validation_alias="DEMO_CORPUS_OCR_EXECUTABLE",
    )
    ocr_language: str = Field(
        default="vie+eng", min_length=1, max_length=64, validation_alias="DEMO_CORPUS_OCR_LANGUAGE"
    )

    def retrieval_source_ids(self) -> tuple[str, ...]:
        values = tuple(
            value.strip().upper()
            for value in self.retrieval_source_ids_csv.split(",")
            if value.strip()
        )
        if not values or len(values) > 3 or len(set(values)) != len(values):
            raise ValueError("DEMO_CORPUS_RETRIEVAL_SOURCE_IDS_INVALID")
        if any(value not in {"VBQPPL", "VNU", "UEB"} for value in values):
            raise ValueError("DEMO_CORPUS_RETRIEVAL_SOURCE_IDS_INVALID")
        return values
