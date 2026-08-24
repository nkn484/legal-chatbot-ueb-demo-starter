"""Focused source-neutral metadata repair retrieval contract tests."""

import asyncio
from uuid import uuid4

import pytest

from legal_chatbot.documents.metadata_repair_repository import (
    MetadataRepairDiagnostics,
    PostgresMetadataRepairRetrievalRepository,
    _Candidate,
    compile_title_tokens,
    compile_title_tsquery,
    extract_document_numbers,
)
from legal_chatbot.retrieval.models import RetrievalRequest


def test_metadata_repair_number_extraction_is_bounded_and_normalized() -> None:
    assert extract_document_numbers("2725 / QĐ– ĐHKT và 12 / 2025 / QH15 và 99/2020/QH") == (
        "2725/qđ-đhkt",
        "12/2025/qh15",
    )


def test_metadata_repair_title_compiler_is_deterministic_and_rejects_singletons() -> None:
    assert compile_title_tokens("quy định về học phí đại học") == ("học", "phí", "đại")
    assert compile_title_tokens("quy định") == ()


def test_title_tsquery_requires_two_of_up_to_four_safe_meaningful_tokens() -> None:
    assert compile_title_tsquery("quy định") == ""
    assert compile_title_tsquery("học phí") == "(học & phí)"
    query = compile_title_tsquery("học phí đại học chính sách")
    assert query == (
        "(học & phí) | (học & đại) | (học & chính) | (phí & đại) | "
        "(phí & chính) | (đại & chính)"
    )
    assert " | học" not in query
    assert query.count("&") == 6


def test_metadata_repair_document_collapse_and_rrf_keep_supporting_child_only() -> None:
    version = uuid4()
    first = _Candidate(uuid4(), version, uuid4(), 1, 0.5, ("semantic",))
    better = _Candidate(uuid4(), version, uuid4(), 0, 0.8, ("semantic",))
    other = _Candidate(uuid4(), uuid4(), uuid4(), 0, 0.7, ("semantic",))
    collapsed = PostgresMetadataRepairRetrievalRepository._collapse((first, better, other))
    assert [item.chunk_id for item in collapsed] == [better.chunk_id, other.chunk_id]
    fused = PostgresMetadataRepairRetrievalRepository._rrf(
        collapsed, (), (better.version_id,), (other.version_id,)
    )
    assert {item.version_id for item in fused} == {better.version_id, other.version_id}
    assert all(item.chunk_id in {better.chunk_id, other.chunk_id} for item in fused)


def test_metadata_repair_observer_is_content_free() -> None:
    observed: list[MetadataRepairDiagnostics] = []
    repository = object.__new__(PostgresMetadataRepairRetrievalRepository)
    repository._observer = observed.append
    diagnostics = MetadataRepairDiagnostics("v6", 20, 1, 2, 1, 0, 23, 16, 16, 0, False, {}, {})
    repository._emit(diagnostics, final_count=3, fallback=True, version="v6_fallback")
    assert observed[0].final_count == 3
    assert observed[0].reranker_fallback is True
    assert str(uuid4()) not in repr(observed[0])


@pytest.mark.asyncio
async def test_read_reenables_title_gin_before_metadata_exact_scans_and_counts_raw_inputs() -> None:
    events: list[str] = []

    class _Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        def begin(self):
            return _Transaction()

        async def execute(self, statement, *_):
            events.append(str(statement))
            return None

    repository = object.__new__(PostgresMetadataRepairRetrievalRepository)
    repository._session_factory = lambda: _Session()
    semantic = tuple(
        _Candidate(uuid4(), uuid4(), uuid4(), ordinal, 1.0 - ordinal / 100, ("semantic",))
        for ordinal in range(20)
    )

    async def select_semantic(*_):
        events.append("semantic")
        return semantic

    async def identities(*_):
        events.append("identity")
        return (semantic[0].version_id,), 0

    async def titles(*_):
        events.append("title")
        return (semantic[1].version_id,)

    async def supporting(*_):
        events.append("supporting")
        return (semantic[0], semantic[1]), 0

    async def hydrate(_, candidates):
        events.append("hydrate")
        return candidates

    repository._semantic = select_semantic
    repository._identity_versions = identities
    repository._title_versions = titles
    repository._supporting_children = supporting
    repository._hydrate = hydrate

    candidates, diagnostics = await repository._read(RetrievalRequest(query="question"), (1.0,))

    assert len(candidates) == 8
    assert events == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "SET LOCAL enable_indexscan = off",
        "SET LOCAL enable_bitmapscan = off",
        "semantic",
        "SET LOCAL enable_indexscan = on",
        "SET LOCAL enable_bitmapscan = on",
        "identity",
        "title",
        "SET LOCAL enable_indexscan = off",
        "SET LOCAL enable_bitmapscan = off",
        "supporting",
        "SET LOCAL enable_indexscan = on",
        "SET LOCAL enable_bitmapscan = on",
        "hydrate",
    ]
    assert diagnostics.semantic_candidate_count == 20
    assert diagnostics.pre_dedup_count == 22
    assert diagnostics.post_document_collapse_count == 16
    assert diagnostics.reranker_input_count == 8
    assert diagnostics.rejection_reason_counts == {
        "DOCUMENT_VERSION_COLLAPSE": 2,
        "SEMANTIC_RANK_CUTOFF": 4,
        "DUPLICATE_CHUNK": 2,
        "RERANK_DEMOTION": 0,
        "FINAL_TOP_K_CUTOFF": 0,
        "IDENTITY_AMBIGUOUS": 0,
        "METADATA_ONLY_NO_SUPPORTING_CHUNK": 0,
    }


@pytest.mark.asyncio
async def test_reranker_failures_fallback_without_swallowing_cancellation() -> None:
    candidate = _Candidate(uuid4(), uuid4(), uuid4(), 0, 0.5, ("semantic",), text="text")
    repository = object.__new__(PostgresMetadataRepairRetrievalRepository)
    repository._timeout_seconds = 0.1

    class _Fails:
        async def rerank(self, _):
            raise RuntimeError("unavailable")

    repository._reranker = _Fails()
    fallback, used_fallback = await repository._rerank(
        RetrievalRequest(query="question"), (candidate,)
    )
    assert fallback == (candidate,)
    assert used_fallback is True

    class _Cancelled:
        async def rerank(self, _):
            raise asyncio.CancelledError

    repository._reranker = _Cancelled()
    with pytest.raises(asyncio.CancelledError):
        await repository._rerank(RetrievalRequest(query="question"), (candidate,))
