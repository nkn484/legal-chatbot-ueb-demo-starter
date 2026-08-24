"""Focused contract coverage for pure M05 retrieval models."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from legal_chatbot.retrieval import (
    EXPANSION_DOCUMENT_IDS_MAX_COUNT,
    EXPANSION_QUERY_MAX_CHARS,
    LEXICAL_STRATEGY,
    LEXICAL_STRATEGY_VERSION,
    QUERY_MAX_CHARS,
    ResolvedCitation,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScope,
    TemporalScope,
)
from legal_chatbot.retrieval.models import RetrievalTrustScope


def _candidate() -> RetrievalCandidate:
    return RetrievalCandidate(
        citation_id=uuid4(),
        document_chunk_id=uuid4(),
        rank=1,
        lexical_score=0.5,
    )


def test_retrieval_candidate_accepts_independent_auditable_scores() -> None:
    base = {"citation_id": uuid4(), "document_chunk_id": uuid4(), "rank": 1}
    assert RetrievalCandidate(**base, lexical_score=0.0).lexical_score == 0.0
    assert RetrievalCandidate(**base, semantic_score=-1.0).semantic_score == -1.0
    assert RetrievalCandidate(**base, lexical_score=0.5, semantic_score=1.0).semantic_score == 1.0
    assert RetrievalCandidate(**base, lexical_score=0.5, reranker_score=42.5).reranker_score == 42.5
    assert (
        RetrievalCandidate(**base, semantic_score=0.5, reranker_score=-42.5).reranker_score == -42.5
    )
    assert RetrievalCandidate(
        **base, lexical_score=0.5, semantic_score=0.5, reranker_score=0.0
    ).reranker_score == 0.0
    invalid_scores = (
        {},
        {"lexical_score": -0.1},
        {"lexical_score": float("nan")},
        {"semantic_score": 1.1},
        {"semantic_score": float("inf")},
        {"lexical_score": 0.5, "reranker_score": float("nan")},
        {"lexical_score": 0.5, "reranker_score": float("inf")},
        {"reranker_score": 0.5},
    )
    for scores in invalid_scores:
        with pytest.raises(ValidationError):
            RetrievalCandidate.model_validate({**base, **scores})


def _result(
    *,
    candidates: tuple[RetrievalCandidate, ...] = (),
    candidate_count: int = 0,
    citation_count: int = 0,
    decision: RetrievalDecision = RetrievalDecision.NO_RESULTS,
    reason: RetrievalReason = RetrievalReason.NO_LEXICAL_MATCH,
) -> RetrievalResult:
    return RetrievalResult(
        retrieval_run_id=uuid4(),
        candidates=candidates,
        candidate_count=candidate_count,
        citation_count=citation_count,
        decision=decision,
        reason=reason,
    )


def test_retrieval_request_strips_query_and_applies_bounds() -> None:
    request = RetrievalRequest(query="  nghĩa vụ thanh toán  ")

    assert request.query == "nghĩa vụ thanh toán"
    assert request.scope is RetrievalScope.LATEST_INGESTED
    assert request.top_k == 10
    assert request.trust_scope is RetrievalTrustScope.STRICT_TLS_ONLY
    assert "query_hash" not in request.model_dump()

    with pytest.raises(ValidationError, match="blank"):
        RetrievalRequest(query=" \t\n ")
    assert QUERY_MAX_CHARS == 4_000
    assert LEXICAL_STRATEGY == "postgresql_fts"
    assert LEXICAL_STRATEGY_VERSION == "v1"
    with pytest.raises(ValidationError, match="4000"):
        RetrievalRequest(query="x" * (QUERY_MAX_CHARS + 1))
    for top_k in (0, 21):
        with pytest.raises(ValidationError):
            RetrievalRequest(query="query", top_k=top_k)


def test_retrieval_request_represents_temporal_intent_and_restricts_scope() -> None:
    as_of_request = RetrievalRequest(query="as of", temporal_scope=TemporalScope.AS_OF)
    assert as_of_request.temporal_scope is TemporalScope.AS_OF
    current_request = RetrievalRequest(query="current", temporal_scope=TemporalScope.CURRENT_EFFECT)
    assert current_request.temporal_scope is TemporalScope.CURRENT_EFFECT
    with pytest.raises(ValueError):
        RetrievalScope("all_versions")
    with pytest.raises(ValidationError):
        RetrievalRequest(query="query", scope="all_versions")  # type: ignore[arg-type]


def test_retrieval_request_requires_bounded_server_scoped_expansion_without_persistence() -> None:
    document_ids = (uuid4(), uuid4())
    request = RetrievalRequest(
        query="câu hỏi gốc",
        expansion_query="  cụm từ mở rộng  ",
        expansion_document_ids=document_ids,
    )

    assert request.query == "câu hỏi gốc"
    assert request.expansion_query == "cụm từ mở rộng"
    assert request.expansion_document_ids == document_ids
    assert "expansion_query" not in request.model_dump()
    assert "expansion_document_ids" not in request.model_dump()
    assert EXPANSION_QUERY_MAX_CHARS == QUERY_MAX_CHARS
    assert EXPANSION_DOCUMENT_IDS_MAX_COUNT == 2
    unscoped_dump = RetrievalRequest(
        query="câu hỏi gốc", expansion_query="unscoped expansion"
    ).model_dump()
    assert unscoped_dump == {
        "query": "câu hỏi gốc",
        "scope": RetrievalScope.LATEST_INGESTED,
        "trust_scope": RetrievalTrustScope.STRICT_TLS_ONLY,
        "top_k": 10,
        "temporal_scope": TemporalScope.NONE,
    }

    invalid_expansions: tuple[dict[str, object], ...] = (
        {"expansion_document_ids": (uuid4(),)},
        {"expansion_query": "   ", "expansion_document_ids": (uuid4(),)},
        {"expansion_query": "câu hỏi gốc", "expansion_document_ids": (uuid4(),)},
        {"expansion_query": "different", "expansion_document_ids": (document_ids[0],) * 2},
        {
            "expansion_query": "different",
            "expansion_document_ids": (uuid4(), uuid4(), uuid4()),
        },
        {
            "expansion_query": "x" * (EXPANSION_QUERY_MAX_CHARS + 1),
            "expansion_document_ids": (uuid4(),),
        },
    )
    for expansion in invalid_expansions:
        with pytest.raises(ValidationError):
            RetrievalRequest.model_validate({"query": "câu hỏi gốc", **expansion})


def test_retrieval_contracts_are_frozen_and_candidate_rejects_invalid_scores() -> None:
    request = RetrievalRequest(query="query")
    with pytest.raises(ValidationError):
        request.top_k = 1  # type: ignore[misc]

    for score in (-0.1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            RetrievalCandidate(
                citation_id=uuid4(),
                document_chunk_id=uuid4(),
                rank=1,
                lexical_score=score,
            )
    with pytest.raises(ValidationError):
        RetrievalCandidate(
            citation_id=uuid4(),
            document_chunk_id=uuid4(),
            rank=0,
            lexical_score=0.0,
        )


def test_retrieval_result_enforces_count_and_decision_invariants() -> None:
    candidate = _candidate()
    evidence = _result(
        candidates=(candidate,),
        candidate_count=1,
        citation_count=1,
        decision=RetrievalDecision.EVIDENCE_AVAILABLE,
    )
    assert evidence.candidates == (candidate,)

    for decision in (
        RetrievalDecision.NO_RESULTS,
        RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
        RetrievalDecision.INVALID_EVIDENCE_CHAIN,
    ):
        assert _result(decision=decision).candidate_count == 0
        with pytest.raises(ValidationError, match="must not include"):
            _result(candidates=(candidate,), candidate_count=1, citation_count=1, decision=decision)

    with pytest.raises(ValidationError, match="requires at least"):
        _result(decision=RetrievalDecision.EVIDENCE_AVAILABLE)
    with pytest.raises(ValidationError, match="candidate_count"):
        _result(candidates=(candidate,), candidate_count=0, citation_count=1)
    with pytest.raises(ValidationError, match="citation_count"):
        _result(candidates=(candidate,), candidate_count=1, citation_count=0)


def test_retrieval_result_rejects_duplicate_ids_and_noncontiguous_ranks() -> None:
    candidate = _candidate()
    duplicate_citation = candidate.model_copy(update={"document_chunk_id": uuid4(), "rank": 2})
    with pytest.raises(ValidationError, match="citation IDs"):
        _result(
            candidates=(candidate, duplicate_citation),
            candidate_count=2,
            citation_count=2,
            decision=RetrievalDecision.EVIDENCE_AVAILABLE,
        )

    duplicate_chunk = candidate.model_copy(update={"citation_id": uuid4(), "rank": 2})
    with pytest.raises(ValidationError, match="chunk IDs"):
        _result(
            candidates=(candidate, duplicate_chunk),
            candidate_count=2,
            citation_count=2,
            decision=RetrievalDecision.EVIDENCE_AVAILABLE,
        )

    with pytest.raises(ValidationError, match="ranks"):
        _result(
            candidates=(candidate.model_copy(update={"rank": 2}),),
            candidate_count=1,
            citation_count=1,
            decision=RetrievalDecision.EVIDENCE_AVAILABLE,
        )


def test_retrieval_result_reason_is_a_restricted_enum() -> None:
    with pytest.raises(ValidationError):
        RetrievalResult(
            retrieval_run_id=uuid4(),
            candidates=(),
            candidate_count=0,
            citation_count=0,
            decision=RetrievalDecision.NO_RESULTS,
            reason="UNSAFE_REASON",  # type: ignore[arg-type]
        )


def test_resolved_citation_excludes_chunk_content_and_allows_json_locator() -> None:
    resolved = ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        source_id="VBQPPL",
        external_id="123",
        locator={"article": "1", "nested": {"clause": 2}},
    )

    assert resolved.locator == {"article": "1", "nested": {"clause": 2}}
    assert "content_text" not in ResolvedCitation.model_fields
