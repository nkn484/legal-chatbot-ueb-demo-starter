"""Safe, normalized errors for the M06 grounded-chat boundary."""

from enum import StrEnum


class ChatErrorCode(StrEnum):
    """Stable failure categories that contain no user, evidence, or provider text."""

    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    GROUNDING_FAILURE = "GROUNDING_FAILURE"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"
    CITATION_REVALIDATION_FAILURE = "CITATION_REVALIDATION_FAILURE"


class ProviderOutputFailureClass(StrEnum):
    """Content-free, stable classifications for rejected provider output."""

    JSON_SYNTAX = "JSON_SYNTAX"
    ROOT_OR_KEYSET = "ROOT_OR_KEYSET"
    ANSWER_TYPE = "ANSWER_TYPE"
    ANSWER_EMPTY_OR_BOUND = "ANSWER_EMPTY_OR_BOUND"
    ANSWER_CONTROL = "ANSWER_CONTROL"
    ANSWER_URL = "ANSWER_URL"
    ANSWER_UUID = "ANSWER_UUID"
    ANSWER_EVIDENCE_TOKEN = "ANSWER_EVIDENCE_TOKEN"
    ANSWER_CITATION_ID = "ANSWER_CITATION_ID"
    ANSWER_UNSAFE_METADATA = "ANSWER_UNSAFE_METADATA"
    PORT_RESULT_TYPE = "PORT_RESULT_TYPE"
    RESPONSE_BYTES = "RESPONSE_BYTES"
    UNKNOWN = "UNKNOWN"


class ChatError(Exception):
    """A code-only exception safe for logs and callers."""

    def __init__(
        self,
        code: ChatErrorCode,
        provider_output_class: ProviderOutputFailureClass | None = None,
    ) -> None:
        if provider_output_class is not None and code is not ChatErrorCode.INVALID_PROVIDER_OUTPUT:
            raise ValueError("provider output class requires INVALID_PROVIDER_OUTPUT")
        self.code = code
        self.provider_output_class = provider_output_class
        super().__init__(code.value)

    def __str__(self) -> str:
        return self.code.value
