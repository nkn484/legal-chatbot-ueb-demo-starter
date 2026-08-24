"""Immutable source/provider-neutral semantic embedding value contracts."""

from __future__ import annotations

from math import fsum, isfinite, sqrt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from legal_chatbot.semantic.constants import (
    SEMANTIC_DIMENSION,
    SEMANTIC_MODEL_ID,
    SEMANTIC_MODEL_REVISION,
    SEMANTIC_NORMALIZATION,
    SEMANTIC_POOLING,
    SEMANTIC_PROFILE_ID,
)


class _FrozenSemanticModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class SemanticProfile(_FrozenSemanticModel):
    """The non-negotiable identity and processing metadata of this vector profile."""

    profile_id: Literal["e5-small-384-mean-l2-prefix-v1"] = SEMANTIC_PROFILE_ID
    model_id: Literal["intfloat/multilingual-e5-small"] = SEMANTIC_MODEL_ID
    revision: Literal["614241f622f53c4eeff9890bdc4f31cfecc418b3"] = SEMANTIC_MODEL_REVISION
    dimension: Literal[384] = SEMANTIC_DIMENSION
    pooling: Literal["mean"] = SEMANTIC_POOLING
    normalization: Literal["l2"] = SEMANTIC_NORMALIZATION


class SemanticEmbeddingBatch(_FrozenSemanticModel):
    """Validated normalized vectors returned without retaining their input text."""

    profile: SemanticProfile = Field(default_factory=SemanticProfile)
    vectors: tuple[tuple[float, ...], ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_vectors(self) -> SemanticEmbeddingBatch:
        for vector in self.vectors:
            if len(vector) != SEMANTIC_DIMENSION:
                raise ValueError("each vector must have exactly 384 dimensions")
            if not all(isfinite(value) for value in vector):
                raise ValueError("each vector value must be finite")
            norm = sqrt(fsum(value * value for value in vector))
            if not isfinite(norm) or norm == 0:
                raise ValueError("each vector must have a finite nonzero L2 norm")
            if abs(norm - 1.0) > 1e-4:
                raise ValueError("each vector must be L2 normalized")
        return self
