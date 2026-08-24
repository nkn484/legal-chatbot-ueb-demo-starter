"""Pure retrieval orchestration over ports; no live search implementation lives here."""

from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    TemporalScope,
)
from legal_chatbot.retrieval.port import RetrievalRepositoryPort


class RetrievalService:
    """Fail closed at the repository boundary while retaining retrieval-only decisions."""

    def __init__(self, repository: RetrievalRepositoryPort) -> None:
        self._repository = repository

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Persist and return bounded evidence, or persist temporal no-evidence intent."""

        try:
            if request.temporal_scope is not TemporalScope.NONE:
                result = await self._repository.persist_zero_evidence_run(
                    request,
                    RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
                    RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED,
                )
            else:
                result = await self._repository.retrieve_and_persist(request)
        except RetrievalError:
            raise
        except Exception:
            raise RetrievalError(RetrievalErrorCode.PERSISTENCE_FAILURE) from None

        return self._validate_repository_result(request, result)

    @staticmethod
    def _validate_repository_result(request: RetrievalRequest, result: object) -> RetrievalResult:
        """Reject malformed port output without retaining its potentially sensitive contents."""

        if not isinstance(result, RetrievalResult):
            raise RetrievalError(RetrievalErrorCode.INVALID_REPOSITORY_RESULT)
        try:
            validated = RetrievalResult.model_validate(result.model_dump())
        except Exception:
            raise RetrievalError(RetrievalErrorCode.INVALID_REPOSITORY_RESULT) from None

        # Private quality state is intentionally absent from model_dump() so it cannot
        # enter logs or persistence. It remains request-local after contract validation.
        if result.quality_context is not None:
            validated = validated.model_copy(update={"quality_context": result.quality_context})
        if validated.candidate_count > request.top_k:
            raise RetrievalError(RetrievalErrorCode.INVALID_REPOSITORY_RESULT)
        if request.temporal_scope is not TemporalScope.NONE and (
            validated.decision is not RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE
            or validated.reason is not RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED
            or validated.candidates
            or validated.candidate_count
            or validated.citation_count
        ):
            raise RetrievalError(RetrievalErrorCode.INVALID_REPOSITORY_RESULT)
        return validated
