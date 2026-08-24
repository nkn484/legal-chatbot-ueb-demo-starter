"""Test-only pure ranking helpers; live retrieval must not call these yet."""

from collections.abc import Iterable
from math import fsum
from uuid import UUID


def reciprocal_rank_fusion(
    rankings: Iterable[Iterable[UUID]], rank_constant: int = 60
) -> tuple[tuple[UUID, float], ...]:
    """Fuse fake ranking lists by RRF, with deterministic score and UUID tie ordering."""

    if rank_constant < 1:
        raise ValueError("rank_constant must be at least 1")

    contributions: dict[UUID, list[float]] = {}
    for ranking in rankings:
        seen: set[UUID] = set()
        for rank, item_id in enumerate(ranking, start=1):
            if item_id in seen:
                raise ValueError("ranking must not contain duplicate IDs")
            seen.add(item_id)
            contributions.setdefault(item_id, []).append(1 / (rank_constant + rank))

    scores = ((item_id, fsum(values)) for item_id, values in contributions.items())
    return tuple(sorted(scores, key=lambda item: (-item[1], item[0])))
