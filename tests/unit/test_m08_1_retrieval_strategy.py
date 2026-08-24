"""M08.1 strategy-version logging tests without a database or planner payload."""

from uuid import uuid4

from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository
from legal_chatbot.retrieval.errors import RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
)


class _CaptureLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def info(self, event: str, *, extra: dict[str, object]) -> None:
        self.calls.append((event, extra))

    def warning(self, event: str, *, extra: dict[str, object]) -> None:
        self.calls.append((event, extra))


def test_expansion_request_logs_explicit_raw_version_after_savepoint_fallback() -> None:
    repository = object.__new__(PostgresLexicalRetrievalRepository)
    logger = _CaptureLogger()
    repository._logger = logger  # type: ignore[assignment]
    request = RetrievalRequest(
        query="original",
        expansion_query="expansion",
        expansion_document_ids=(uuid4(),),
    )
    result = RetrievalResult(
        retrieval_run_id=uuid4(),
        candidates=(),
        candidate_count=0,
        citation_count=0,
        decision=RetrievalDecision.NO_RESULTS,
        reason=RetrievalReason.NO_LEXICAL_MATCH,
    )

    repository._log_complete(request, result, "v3_lexical_repair")
    repository._log_failure(request, RetrievalErrorCode.PERSISTENCE_FAILURE, "v3_lexical_repair")

    assert logger.calls[0][1]["retrieval_strategy_version"] == "v3_lexical_repair"
    assert logger.calls[1][1]["retrieval_strategy_version"] == "v3_lexical_repair"
    assert (
        logger.calls[1][1]["retrieval_error_code"] == RetrievalErrorCode.PERSISTENCE_FAILURE.value
    )
