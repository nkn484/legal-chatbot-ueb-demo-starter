"""Focused service-boundary coverage for pure M05 retrieval orchestration."""

import ast
import inspect
from typing import cast
from uuid import uuid4

import pytest

import legal_chatbot.retrieval.service as service_module
from legal_chatbot.retrieval import (
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalError,
    RetrievalErrorCode,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    RetrievalService,
    TemporalScope,
)


def _result(
    *,
    candidates: tuple[RetrievalCandidate, ...] = (),
    decision: RetrievalDecision = RetrievalDecision.NO_RESULTS,
    reason: RetrievalReason = RetrievalReason.NO_LEXICAL_MATCH,
) -> RetrievalResult:
    return RetrievalResult(
        retrieval_run_id=uuid4(),
        candidates=candidates,
        candidate_count=len(candidates),
        citation_count=len(candidates),
        decision=decision,
        reason=reason,
    )


def _candidate(rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        citation_id=uuid4(),
        document_chunk_id=uuid4(),
        rank=rank,
        lexical_score=1.0 / rank,
    )


class FakeRepository:
    def __init__(self, result: object) -> None:
        self.result = result
        self.retrieve_calls: list[RetrievalRequest] = []
        self.zero_evidence_calls: list[
            tuple[RetrievalRequest, RetrievalDecision, RetrievalReason]
        ] = []

    async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
        self.retrieve_calls.append(request)
        return cast(RetrievalResult, self.result)

    async def persist_zero_evidence_run(
        self,
        request: RetrievalRequest,
        decision: RetrievalDecision,
        reason: RetrievalReason,
    ) -> RetrievalResult:
        self.zero_evidence_calls.append((request, decision, reason))
        return cast(RetrievalResult, self.result)


@pytest.mark.asyncio
async def test_temporal_request_only_persists_unsupported_zero_evidence_run() -> None:
    expected = _result(
        decision=RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
        reason=RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED,
    )
    repository = FakeRepository(expected)
    request = RetrievalRequest(query="as of query", temporal_scope=TemporalScope.AS_OF)

    assert await RetrievalService(repository).retrieve(request) == expected
    assert repository.retrieve_calls == []
    assert repository.zero_evidence_calls == [
        (
            request,
            RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
            RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED,
        )
    ]


@pytest.mark.asyncio
async def test_normal_request_delegates_to_retrieve_and_persist_exactly_once() -> None:
    candidate = _candidate(rank=1)
    expected = _result(
        candidates=(candidate,),
        decision=RetrievalDecision.EVIDENCE_AVAILABLE,
        reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
    )
    repository = FakeRepository(expected)
    request = RetrievalRequest(query="lexical query")

    assert await RetrievalService(repository).retrieve(request) == expected
    assert repository.retrieve_calls == [request]
    assert repository.zero_evidence_calls == []


@pytest.mark.asyncio
async def test_service_keeps_request_local_quality_context_out_of_public_serialization() -> None:
    candidate = _candidate(rank=1)
    context = object()
    expected = _result(
        candidates=(candidate,),
        decision=RetrievalDecision.EVIDENCE_AVAILABLE,
        reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
    ).model_copy(update={"quality_context": context})

    result = await RetrievalService(FakeRepository(expected)).retrieve(
        RetrievalRequest(query="query")
    )

    assert result.quality_context is context
    assert "quality_context" not in result.model_dump()


@pytest.mark.asyncio
async def test_service_rejects_result_exceeding_request_top_k() -> None:
    result = _result(
        candidates=(_candidate(rank=1), _candidate(rank=2)),
        decision=RetrievalDecision.EVIDENCE_AVAILABLE,
        reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
    )

    with pytest.raises(RetrievalError) as raised:
        await RetrievalService(FakeRepository(result)).retrieve(
            RetrievalRequest(query="query", top_k=1)
        )

    assert raised.value.code is RetrievalErrorCode.INVALID_REPOSITORY_RESULT


@pytest.mark.parametrize("malformed", (None, {"query": "RAW_QUERY_SENTINEL"}))
@pytest.mark.asyncio
async def test_service_normalizes_wrong_repository_result(malformed: object) -> None:
    with pytest.raises(RetrievalError) as raised:
        await RetrievalService(FakeRepository(cast(RetrievalResult, malformed))).retrieve(
            RetrievalRequest(query="RAW_QUERY_SENTINEL")
        )

    assert raised.value.code is RetrievalErrorCode.INVALID_REPOSITORY_RESULT
    assert str(raised.value) == RetrievalErrorCode.INVALID_REPOSITORY_RESULT.value
    assert "RAW_QUERY_SENTINEL" not in str(raised.value)


@pytest.mark.asyncio
async def test_service_preserves_safe_errors_and_normalizes_unexpected_causes() -> None:
    class RaisingRepository(FakeRepository):
        async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
            raise RetrievalError(RetrievalErrorCode.CITATION_NOT_FOUND)

    with pytest.raises(RetrievalError) as raised:
        await RetrievalService(RaisingRepository(None)).retrieve(RetrievalRequest(query="query"))
    assert raised.value.code is RetrievalErrorCode.CITATION_NOT_FOUND

    class UnexpectedRepository(FakeRepository):
        async def retrieve_and_persist(self, request: RetrievalRequest) -> RetrievalResult:
            raise RuntimeError("RAW_QUERY_SENTINEL CHUNK_TEXT_SENTINEL")

    with pytest.raises(RetrievalError) as raised:
        await RetrievalService(UnexpectedRepository(None)).retrieve(RetrievalRequest(query="query"))
    assert raised.value.code is RetrievalErrorCode.PERSISTENCE_FAILURE
    assert str(raised.value) == RetrievalErrorCode.PERSISTENCE_FAILURE.value
    assert "RAW_QUERY_SENTINEL" not in str(raised.value)
    assert "CHUNK_TEXT_SENTINEL" not in str(raised.value)


def test_service_has_no_live_ranking_or_external_adapter_imports() -> None:
    parsed = ast.parse(inspect.getsource(service_module))
    imported_modules = {
        alias.name
        for statement in ast.walk(parsed)
        if isinstance(statement, ast.Import)
        for alias in statement.names
    }
    imported_modules.update(
        statement.module or ""
        for statement in ast.walk(parsed)
        if isinstance(statement, ast.ImportFrom)
    )

    forbidden = (
        "sqlalchemy",
        "pgvector",
        "provider",
        "sources",
        "chat",
        "channel",
        "api",
        "ranking",
    )
    assert not any(
        imported == blocked or imported.startswith(f"{blocked}.")
        for imported in imported_modules
        for blocked in forbidden
    )
    assert "reciprocal_rank_fusion" not in inspect.getsource(service_module)
