"""Focused unit coverage for the fake-list-only RRF helper."""

from math import isclose
from uuid import UUID

import pytest

from legal_chatbot.retrieval.ranking import reciprocal_rank_fusion


def test_reciprocal_rank_fusion_sums_scores_and_sorts_descending() -> None:
    first = UUID(int=1)
    second = UUID(int=2)

    fused = reciprocal_rank_fusion(((first,), (second, first)))

    assert [item_id for item_id, _score in fused] == [first, second]
    assert isclose(fused[0][1], 1 / 61 + 1 / 62)
    assert isclose(fused[1][1], 1 / 61)


def test_reciprocal_rank_fusion_uses_uuid_order_for_score_ties() -> None:
    lower_id = UUID(int=3)
    higher_id = UUID(int=4)

    fused = reciprocal_rank_fusion(((higher_id,), (lower_id,)))

    assert fused == ((lower_id, 1 / 61), (higher_id, 1 / 61))


def test_reciprocal_rank_fusion_allows_ids_across_rankings_but_not_within_one() -> None:
    item_id = UUID(int=5)

    assert reciprocal_rank_fusion(((item_id,), (item_id,))) == ((item_id, 2 / 61),)
    with pytest.raises(ValueError, match="duplicate"):
        reciprocal_rank_fusion(((item_id, item_id),))


@pytest.mark.parametrize("rank_constant", (0, -1))
def test_reciprocal_rank_fusion_rejects_invalid_rank_constant(rank_constant: int) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        reciprocal_rank_fusion((), rank_constant=rank_constant)
