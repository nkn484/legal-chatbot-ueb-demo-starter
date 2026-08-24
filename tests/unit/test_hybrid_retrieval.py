"""Focused unit coverage for exact offline semantic and hybrid retrieval."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from legal_chatbot.documents.hybrid_retrieval_repository import (
    PostgresHybridRetrievalRepository,
    _Candidate,
)
from legal_chatbot.retrieval.models import RetrievalReason, RetrievalRequest
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode
from legal_chatbot.semantic.models import SemanticEmbeddingBatch


def _vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


class _Result:
    def __init__(self, rows: tuple[object, ...] = ()) -> None:
        self._rows = rows

    def all(self) -> tuple[object, ...]:
        return self._rows


class _Session:
    def __init__(self, events: list[str], *, missing: int = 0) -> None:
        self.events = events
        self.missing = missing
        self.added: list[object] = []

    async def scalar(self, statement: object) -> int:
        del statement
        self.events.append("coverage")
        return self.missing

    async def execute(self, statement: object, params: object = None) -> _Result:
        del params
        self.events.append(getattr(statement, "text", "statement"))
        return _Result()

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        self.events.append("begin")
        yield

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        return None


class _Factory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[_Session]:
        yield self.session


class _Embedder:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        del text
        self.events.append("embed")
        if self.fail:
            raise SemanticError(SemanticErrorCode.MODEL_UNAVAILABLE)
        return SemanticEmbeddingBatch(vectors=(_vector(),))

    async def embed_documents(self, texts: object) -> SemanticEmbeddingBatch:
        raise AssertionError(texts)


@pytest.mark.asyncio
async def test_hybrid_retrieval_embeds_before_transaction_and_forces_exact_scan() -> None:
    events: list[str] = []
    session = _Session(events)
    repository = PostgresHybridRetrievalRepository(
        _Factory(session), ("VBQPPL",), _Embedder(events), mode="semantic"  # type: ignore[arg-type]
    )

    async def ready() -> bool:
        return True

    repository.coverage_complete = ready  # type: ignore[method-assign]
    await repository.retrieve_and_persist(RetrievalRequest(query="nghĩa vụ"))

    assert events[0] == "embed"
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in events[2]
    assert "SET LOCAL enable_indexscan = off" in events
    assert "SET LOCAL enable_bitmapscan = off" in events
    assert "SET LOCAL enable_indexscan = on" in events
    assert "SET LOCAL enable_bitmapscan = on" in events


@pytest.mark.asyncio
async def test_hybrid_retrieval_coverage_requires_exact_semantic_rows() -> None:
    complete = await PostgresHybridRetrievalRepository.coverage_complete_for(
        _Factory(_Session([], missing=0)), ("VBQPPL",)  # type: ignore[arg-type]
    )
    incomplete = await PostgresHybridRetrievalRepository.coverage_complete_for(
        _Factory(_Session([], missing=1)), ("VBQPPL",)  # type: ignore[arg-type]
    )
    assert complete is True
    assert incomplete is False


@pytest.mark.asyncio
async def test_hybrid_retrieval_semantic_failure_falls_back_only_in_hybrid() -> None:
    events: list[str] = []
    session = _Session(events)
    hybrid = PostgresHybridRetrievalRepository(
        _Factory(session), ("VBQPPL",), _Embedder(events, fail=True), mode="hybrid"  # type: ignore[arg-type]
    )
    result = await hybrid.retrieve_and_persist(RetrievalRequest(query="nghĩa vụ"))
    assert result.candidate_count == 0
    assert session.added[0].strategy_version == "v4_hybrid_semantic_fallback"  # type: ignore[attr-defined]

    semantic_session = _Session([])
    semantic = PostgresHybridRetrievalRepository(
        _Factory(semantic_session), ("VBQPPL",), _Embedder([], fail=True), mode="semantic"  # type: ignore[arg-type]
    )
    zero = await semantic.retrieve_and_persist(RetrievalRequest(query="nghĩa vụ"))
    assert zero.candidate_count == 0
    assert semantic_session.added[0].strategy_version == "v4_semantic_exact"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_hybrid_retrieval_existing_persistence_leaves_reranker_score_null() -> None:
    session = _Session([])
    repository = PostgresHybridRetrievalRepository(
        _Factory(session), ("VBQPPL",), _Embedder([]), mode="semantic"  # type: ignore[arg-type]
    )
    version_id = uuid4()
    candidate = _Candidate(uuid4(), version_id, uuid4(), version_id, semantic_score=0.5)
    result = await repository._persist(
        session,
        RetrievalRequest(query="nghĩa vụ"),
        (candidate,),
        strategy="postgresql_semantic",
        strategy_version="v4_semantic_exact",
        reason=RetrievalReason.SEMANTIC_EVIDENCE_AVAILABLE,
    )
    citation = next(item for item in session.added if item.__class__.__name__ == "CitationRecord")
    assert citation.reranker_score is None
    assert result.candidates[0].reranker_score is None


def test_hybrid_retrieval_fusion_dedupes_and_retains_raw_top_one() -> None:
    raw_top, raw_other, semantic_top = uuid4(), uuid4(), uuid4()
    raw = (
        _Candidate(raw_top, uuid4(), uuid4(), None, lexical_score=0.9),
        _Candidate(raw_other, uuid4(), uuid4(), None, lexical_score=0.8),
    )
    semantic = (
        _Candidate(semantic_top, uuid4(), uuid4(), None, semantic_score=0.9),
        _Candidate(raw_other, raw[1].version_id, raw[1].provenance_id, None, semantic_score=0.8),
    )
    ranked = PostgresHybridRetrievalRepository._rank_hybrid(raw, semantic, 2)
    assert {row.chunk_id for row in ranked} == {raw_top, raw_other}
    assert len(ranked) == 2


def test_hybrid_retrieval_reasons_distinguish_semantic_and_hybrid_evidence() -> None:
    assert RetrievalReason.SEMANTIC_EVIDENCE_AVAILABLE.value == "SEMANTIC_EVIDENCE_AVAILABLE"
    assert RetrievalReason.HYBRID_EVIDENCE_AVAILABLE.value == "HYBRID_EVIDENCE_AVAILABLE"
    assert RetrievalReason.NO_SEMANTIC_MATCH.value == "NO_SEMANTIC_MATCH"
    assert RetrievalReason.SEMANTIC_UNAVAILABLE.value == "SEMANTIC_UNAVAILABLE"
