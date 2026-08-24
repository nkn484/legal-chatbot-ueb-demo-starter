"""Safe, normalized legal source exceptions."""

from legal_chatbot.sources.models import SourceErrorCode


def _safe_label(value: str, *, fallback: str) -> str:
    """Keep only compact printable labels out of source error metadata."""
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 128
        or any(not "!" <= item <= "~" for item in normalized)
    ):
        return fallback
    return normalized


class SourceError(Exception):
    """Source failure carrying only normalized operational metadata."""

    def __init__(
        self,
        code: SourceErrorCode,
        *,
        source_id: str = "unknown",
        operation: str = "unknown",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.source_id = _safe_label(source_id, fallback="unknown")
        self.operation = _safe_label(operation, fallback="unknown")
        self.retryable = retryable
        self.status_code = status_code
        super().__init__(code.value)

    def __str__(self) -> str:
        """Never expose remote response text or implementation details."""
        return self.code.value
