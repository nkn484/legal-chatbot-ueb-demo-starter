"""Safe retrieval errors that never expose untrusted query or database details."""

from enum import StrEnum


class RetrievalErrorCode(StrEnum):
    """Stable error categories at the retrieval service boundary."""

    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    INVALID_REPOSITORY_RESULT = "INVALID_REPOSITORY_RESULT"
    CITATION_NOT_FOUND = "CITATION_NOT_FOUND"
    CITATION_RUN_MISMATCH = "CITATION_RUN_MISMATCH"
    INVALID_EVIDENCE_CHAIN = "INVALID_EVIDENCE_CHAIN"


class RetrievalError(Exception):
    """A normalized error whose string form is safe to log or expose."""

    def __init__(self, code: RetrievalErrorCode) -> None:
        self.code = code
        super().__init__(code.value)

    def __str__(self) -> str:
        return self.code.value
