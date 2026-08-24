"""Safe placeholder for source systems intentionally deferred beyond the demo."""

from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import (
    FetchApprovedDocumentRef,
    LegalDocumentSnapshot,
    SourceErrorCode,
    SourceHealth,
)
from legal_chatbot.sources.registry import SourceSystemConfig


class NotImplementedSourceAdapter:
    """Raise a normalized error without constructing a client or making network calls."""

    def __init__(self, source: SourceSystemConfig) -> None:
        self._source_id = source.id

    def _error(self, operation: str) -> SourceError:
        return SourceError(
            SourceErrorCode.SOURCE_NOT_IMPLEMENTED,
            source_id=self._source_id,
            operation=operation,
            retryable=False,
        )

    async def list_documents(self) -> tuple[FetchApprovedDocumentRef, ...]:
        raise self._error("list_documents")

    async def fetch_document(self, ref: FetchApprovedDocumentRef) -> LegalDocumentSnapshot:
        del ref
        raise self._error("fetch_document")

    async def health_check(self) -> SourceHealth:
        raise self._error("health_check")

    async def aclose(self) -> None:
        """Release no resources: this adapter never constructs a transport client."""
