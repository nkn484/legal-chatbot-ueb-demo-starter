"""Safe, typed semantic embedding failures."""

from __future__ import annotations

from enum import StrEnum


class SemanticErrorCode(StrEnum):
    """Stable content-free failure codes for this offline-only lane."""

    INVALID_INPUT = "invalid_input"
    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_ARTIFACT_INVALID = "model_artifact_invalid"
    EMBEDDING_FAILED = "embedding_failed"
    INVALID_VECTOR = "invalid_vector"
    PERSISTENCE_FAILURE = "persistence_failure"


class SemanticError(RuntimeError):
    """An error that exposes only a safe category, never source text or paths."""

    def __init__(self, code: SemanticErrorCode) -> None:
        self.code = code
        super().__init__(code.value)
