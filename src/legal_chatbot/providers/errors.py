"""Safe, normalized provider exceptions."""

from legal_chatbot.providers.models import ProviderErrorCode, sanitize_request_id


class ProviderError(Exception):
    """Provider failure that carries only normalized, non-provider-body metadata."""

    def __init__(
        self,
        code: ProviderErrorCode,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.request_id = sanitize_request_id(request_id)
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code.value)
