"""Immutable, source-neutral contracts used at the ingestion boundary."""

from enum import StrEnum
from hashlib import sha256
from math import fsum, isfinite, sqrt
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

BlockKind = Literal["paragraph", "chapter", "section", "article", "clause", "item"]


class _FrozenIngestionModel(BaseModel):
    """Base for value-like ingestion data passed between pipeline stages."""

    model_config = ConfigDict(frozen=True)


class NormalizedBlock(_FrozenIngestionModel):
    """A stable text range, optionally classified from an explicit HTML class."""

    kind: BlockKind
    label: str | None = Field(default=None, min_length=1, max_length=1_024)
    text: str = Field(min_length=1, max_length=2_097_152)
    start: int = Field(ge=0)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> "NormalizedBlock":
        """Use conventional inclusive-start, exclusive-end text offsets."""
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.end - self.start != len(self.text):
            raise ValueError("block range must match text length")
        return self


class NormalizedDocument(_FrozenIngestionModel):
    """Canonical text and its deterministic HTML-normalization output."""

    text: str = Field(min_length=1, max_length=2_097_152)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blocks: tuple[NormalizedBlock, ...] = Field(min_length=1)
    normalizer_version: Literal["html-v1"]

    @model_validator(mode="after")
    def validate_text_hash_and_blocks(self) -> "NormalizedDocument":
        """Keep the declared hash and block offsets bound to canonical text."""
        if self.sha256 != sha256(self.text.encode("utf-8")).hexdigest():
            raise ValueError("sha256 must match normalized text")
        for block in self.blocks:
            if self.text[block.start : block.end] != block.text:
                raise ValueError("block range must resolve to its text")
        return self


class ChunkDraft(_FrozenIngestionModel):
    """A not-yet-persisted chunk derived from one normalized document version."""

    ordinal: int = Field(ge=0)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=8_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunker_version: Literal["legal-block-v1"]
    locator: dict[str, str] | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "ChunkDraft":
        """Require chunk offsets to describe precisely the chunk text."""
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.end - self.start != len(self.text):
            raise ValueError("chunk range must match text length")
        if self.content_sha256 != sha256(self.text.encode("utf-8")).hexdigest():
            raise ValueError("content_sha256 must match chunk text")
        return self


class EmbeddingKind(StrEnum):
    """Embedding semantics available in this demo milestone."""

    DEMO_NON_SEMANTIC = "demo_non_semantic"


class EmbeddingBatch(_FrozenIngestionModel):
    """A bounded, explicitly non-semantic vector batch."""

    model_id: Literal["local-hash-v1"] = "local-hash-v1"
    dimension: Literal[384] = 384
    embedding_kind: EmbeddingKind = EmbeddingKind.DEMO_NON_SEMANTIC
    vectors: tuple[tuple[float, ...], ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_vectors(self) -> "EmbeddingBatch":
        """Reject vectors that cannot be safely persisted or queried."""
        if any(len(vector) != self.dimension for vector in self.vectors):
            raise ValueError("each vector must match embedding dimension")
        for vector in self.vectors:
            if not all(isfinite(value) for value in vector):
                raise ValueError("each vector value must be finite")
            norm = sqrt(fsum(value * value for value in vector))
            if not isfinite(norm) or norm == 0:
                raise ValueError("each vector must have a finite nonzero L2 norm")
        return self


class IngestionOutcome(StrEnum):
    """Idempotent ingestion result states."""

    CREATED = "created"
    UNCHANGED = "unchanged"


class IngestionResult(_FrozenIngestionModel):
    """Source-neutral summary of an ingestion attempt."""

    document_id: UUID
    document_version_id: UUID
    version_number: int = Field(ge=1)
    outcome: IngestionOutcome
    block_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    embedding_count: int = Field(ge=0)
    embedding_model_id: Literal["local-hash-v1"] = "local-hash-v1"
    semantic_ready: Literal[False] = False
