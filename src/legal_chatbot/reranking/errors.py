"""Safe, typed failures for the isolated offline reranking lane."""

from __future__ import annotations

from enum import StrEnum


class RerankerErrorCode(StrEnum):
    """Stable, content-free failure categories."""

    INVALID_INPUT = "invalid_input"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_ARTIFACT_INVALID = "model_artifact_invalid"
    RERANK_FAILED = "rerank_failed"
    INVALID_RESULT = "invalid_result"


class RerankerError(RuntimeError):
    """An error containing only a safe category, never text or filesystem details."""

    def __init__(self, code: RerankerErrorCode) -> None:
        self.code = code
        super().__init__(code.value)
