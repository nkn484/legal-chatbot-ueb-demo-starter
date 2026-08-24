"""Focused bounded exact-semantic reranking repository checks."""

from __future__ import annotations

from uuid import uuid4

import pytest

from legal_chatbot.documents.reranked_semantic_repository import (
    PostgresRerankedSemanticRepository,
    RerankedRetrievalDiagnostics,
    _SemanticChild,
)
from legal_chatbot.reranking.models import RerankResult


def _child(version_id=None, *, score: float = 0.5, ordinal: int = 0) -> _SemanticChild:
    return _SemanticChild(uuid4(), version_id or uuid4(), uuid4(), ordinal, score, "child")


def test_reranked_retrieval_collapses_versions_and_uses_deterministic_ties() -> None:
    version_id = uuid4()
    weaker = _child(version_id, score=0.4, ordinal=0)
    stronger = _child(version_id, score=0.8, ordinal=1)
    other = _child(score=0.7)
    collapsed = PostgresRerankedSemanticRepository._collapse_versions((weaker, stronger, other))
    assert [item.chunk_id for item in collapsed] == [stronger.chunk_id, other.chunk_id]


def test_reranked_retrieval_applies_aligned_raw_logits_without_fusion() -> None:
    first = _child(score=0.9)
    second = _child(score=0.8)
    result = RerankResult(
        candidate_ids=(str(first.chunk_id), str(second.chunk_id)), scores=(-2.0, 3.0)
    )
    ranked = PostgresRerankedSemanticRepository._apply_rerank((first, second), result)
    assert [item.chunk_id for item in ranked] == [second.chunk_id, first.chunk_id]
    assert [item.reranker_score for item in ranked] == [3.0, -2.0]


def test_reranked_retrieval_rejects_misaligned_result_for_fallback() -> None:
    child = _child()
    result = RerankResult(candidate_ids=(str(uuid4()),), scores=(1.0,))
    with pytest.raises(ValueError, match="alignment"):
        PostgresRerankedSemanticRepository._apply_rerank((child,), result)


@pytest.mark.asyncio
async def test_reranked_retrieval_hydrates_only_adjacent_ordinals_and_caps_text() -> None:
    version_id = uuid4()
    child = _SemanticChild(uuid4(), version_id, uuid4(), 5, 0.5)
    observed: list[object] = []

    class Result:
        def all(self):
            return (
                (version_id, 4, "p" * 500, None),
                (version_id, 5, "c" * 1_500, {"label": "Article 1"}),
                (version_id, 6, "s" * 500, None),
            )

    class Session:
        async def execute(self, statement):
            observed.append(statement)
            return Result()

    repository = object.__new__(PostgresRerankedSemanticRepository)
    hydrated = await repository._hydrate(Session(), (child,))
    assert len(observed) == 1
    assert len(hydrated[0].text) == 2_000
    assert "Article 1" in hydrated[0].text
    compiled = str(observed[0])
    assert "document_chunks.ordinal IN" in compiled
    assert "ORDER BY" not in compiled


@pytest.mark.asyncio
async def test_reranked_retrieval_timeout_uses_exact_fallback_without_score() -> None:
    child = _child()

    class SlowReranker:
        async def rerank(self, request):
            del request
            await __import__("asyncio").sleep(0.01)
            raise AssertionError

    repository = object.__new__(PostgresRerankedSemanticRepository)
    repository._reranker = SlowReranker()
    repository._timeout_seconds = 0.001
    ranked, fallback = await repository._rerank(type("Request", (), {"query": "query"})(), (child,))
    assert fallback is True
    assert ranked == (child,)
    assert ranked[0].reranker_score is None


def test_reranked_retrieval_diagnostics_are_content_free_counts_only() -> None:
    emitted: list[RerankedRetrievalDiagnostics] = []
    repository = object.__new__(PostgresRerankedSemanticRepository)
    repository._observer = emitted.append
    repository._emit("v5_semantic_exact_reranker_fallback", 8, 3, 3, 2, True)
    assert emitted == [
        RerankedRetrievalDiagnostics(
            strategy_version="v5_semantic_exact_reranker_fallback",
            pre_rerank_chunk_candidate_count=8,
            pre_rerank_document_version_count=3,
            post_collapse_document_version_count=3,
            final_citation_document_version_count=2,
            reranker_fallback=True,
        )
    ]
    assert "chunk_id" not in repr(emitted[0])
