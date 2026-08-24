"""Immutable contracts for the approved manual demo corpus."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CorpusFileKind(StrEnum):
    DIRECT_FILE = "DIRECT_FILE"
    FOLDER = "FOLDER"
    MISSING = "MISSING"
    UNRESOLVED = "UNRESOLVED"


class CorpusProcessingStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    FILE_PENDING = "FILE_PENDING"
    FILE_DOWNLOADED = "FILE_DOWNLOADED"
    EXTRACTED = "EXTRACTED"
    OCR_REQUIRED = "OCR_REQUIRED"
    CHUNKED = "CHUNKED"
    INDEXED = "INDEXED"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class CatalogEntry(_FrozenModel):
    dataset_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(pattern=r"^(VBQPPL|VNU|UEB)$")
    workbook_name: str = Field(min_length=1, max_length=512)
    sheet_name: str = Field(min_length=1, max_length=128)
    source_row: int = Field(ge=2)
    external_id: str = Field(min_length=1, max_length=256)
    document_number: str | None = Field(default=None, max_length=256)
    title: str | None = Field(default=None, max_length=4_096)
    document_type: str | None = Field(default=None, max_length=512)
    issuing_authority: str | None = Field(default=None, max_length=1_024)
    issue_date: datetime | None = None
    effective_date: datetime | None = None
    legal_status: str | None = Field(default=None, max_length=256)
    file_label: str | None = Field(default=None, max_length=2_048)
    file_url: str | None = Field(default=None, max_length=2_048)
    file_kind: CorpusFileKind
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("issue_date", "effective_date")
    @classmethod
    def validate_aware_dates(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("catalog dates must be timezone-aware")
        return value


class ExtractedPage(_FrozenModel):
    page_number: int = Field(ge=1)
    text: str = Field(max_length=2_097_152)


class ExtractedDocument(_FrozenModel):
    pages: tuple[ExtractedPage, ...] = Field(min_length=1)
    used_ocr: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())


class DownloadedAsset(_FrozenModel):
    content: bytes = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_type: str = Field(min_length=1, max_length=256)
