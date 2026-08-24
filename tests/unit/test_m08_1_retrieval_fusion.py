"""Pure M08.1 retrieval-fusion invariants without database or planner content."""

from uuid import UUID

from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
)


def _uuid(value: int) -> UUID:
    return UUID(int=value)


def _row(value: int, score: float = 1.0) -> _CandidateRow:
    version_id = _uuid(100 + value)
    return _CandidateRow(_uuid(value), version_id, _uuid(200 + value), version_id, score)


def test_raw_only_fusion_matches_raw_rank_order_and_preserves_lexical_scores() -> None:
    raw = (_row(3, 0.8), _row(2, 0.7), _row(1, 0.6))

    final = PostgresLexicalRetrievalRepository._fuse_candidates(raw, (), (), top_k=2)

    assert final == raw[:2]
    assert tuple(candidate.lexical_score for candidate in final) == (0.8, 0.7)


def test_weighted_rrf_deduplicates_uses_repair_score_and_breaks_ties_deterministically() -> None:
    raw = (_row(5, 0.9), _row(3, 0.8))
    repair = (_row(3, 0.1), _row(1, 0.2), _row(2, 0.3))

    final = PostgresLexicalRetrievalRepository._fuse_candidates(raw, repair, (), top_k=4)

    assert tuple(candidate.document_chunk_id for candidate in final) == (
        _uuid(3),
        _uuid(1),
        _uuid(2),
        _uuid(5),
    )
    assert final[0].lexical_score == 0.1

    tied_raw = (_row(9),)
    tied_expansion = (_row(8),)
    tied_final = PostgresLexicalRetrievalRepository._fuse_candidates(
        tied_raw, (), tied_expansion, top_k=2
    )
    assert tuple(candidate.document_chunk_id for candidate in tied_final) == (_uuid(9), _uuid(8))


def test_raw_rank_one_is_retained_when_fusion_would_exclude_it_at_top_one() -> None:
    raw = (_row(1),)
    repair = tuple(_row(value) for value in (2, 3, 4, 5, 6))

    final = PostgresLexicalRetrievalRepository._fuse_candidates(raw, repair, (), top_k=1)

    assert final == raw


def test_candidate_limit_is_top_k_plus_two_capped_at_eight() -> None:
    assert PostgresLexicalRetrievalRepository._candidate_limit(1) == 3
    assert PostgresLexicalRetrievalRepository._candidate_limit(4) == 6
    assert PostgresLexicalRetrievalRepository._candidate_limit(20) == 8
