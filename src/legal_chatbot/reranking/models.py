"""Immutable, provider-neutral contracts for bounded reranking."""

from __future__ import annotations

from math import isfinite
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.reranking.constants import (
    ONNX_MODEL_FILE,
    RERANKER_CANDIDATE_MAX,
    RERANKER_HYDRATED_TEXT_MAX_CHARS,
    RERANKER_LICENSE,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    RERANKER_PROFILE_ID,
    RERANKER_QUERY_MAX_CHARS,
)


class _FrozenRerankingModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class RerankerProfile(_FrozenRerankingModel):
    """Non-negotiable identity of the AVX2 cross-encoder profile."""

    profile_id: Literal["mmarco-minilm-l12-h384-int8-avx2-v1"] = RERANKER_PROFILE_ID
    model_id: Literal["cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"] = RERANKER_MODEL_ID
    revision: Literal["1427fd652930e4ba29e8149678df786c240d8825"] = RERANKER_MODEL_REVISION
    model_file: Literal["onnx/model_quint8_avx2.onnx"] = ONNX_MODEL_FILE
    license: Literal["Apache-2.0"] = RERANKER_LICENSE
    required_cpu_feature: Literal["AVX2"] = "AVX2"


class RerankCandidate(_FrozenRerankingModel):
    """An opaque chunk reference paired only with its bounded hydrated text."""

    chunk_id: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=RERANKER_HYDRATED_TEXT_MAX_CHARS)

    @field_validator("chunk_id", "text")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value


class RerankRequest(_FrozenRerankingModel):
    """One bounded query and its ordered, unique candidate set."""

    query: str = Field(min_length=1, max_length=RERANKER_QUERY_MAX_CHARS)
    candidates: tuple[RerankCandidate, ...] = Field(
        min_length=1, max_length=RERANKER_CANDIDATE_MAX
    )

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        ids = tuple(candidate.chunk_id for candidate in self.candidates)
        if len(set(ids)) != len(ids):
            raise ValueError("candidate chunk IDs must be unique")
        return self


class RerankResult(_FrozenRerankingModel):
    """Raw cross-encoder logits aligned in order to the supplied candidate IDs."""

    profile: RerankerProfile = Field(default_factory=RerankerProfile)
    candidate_ids: tuple[str, ...] = Field(min_length=1, max_length=RERANKER_CANDIDATE_MAX)
    scores: tuple[float, ...] = Field(min_length=1, max_length=RERANKER_CANDIDATE_MAX)

    @model_validator(mode="after")
    def validate_alignment(self) -> Self:
        if len(self.candidate_ids) != len(self.scores):
            raise ValueError("scores must align exactly with candidate IDs")
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate IDs must be unique")
        if any(not candidate_id.strip() for candidate_id in self.candidate_ids):
            raise ValueError("candidate IDs must not be blank")
        if not all(isfinite(score) for score in self.scores):
            raise ValueError("raw logits must be finite")
        return self

    @classmethod
    def from_request(cls, request: RerankRequest, scores: tuple[float, ...]) -> Self:
        """Build the sole valid result mapping for an input request."""

        return cls(candidate_ids=tuple(item.chunk_id for item in request.candidates), scores=scores)
