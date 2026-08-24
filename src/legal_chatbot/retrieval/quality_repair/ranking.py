"""Pure Phase-B1 chunk merging, document collapse, fusion, and pool selection."""

from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum
from math import isclose, isfinite
from typing import Final, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .models import (
    CandidateEvidence,
    CollapsedDocumentCandidate,
    DocumentIdentity,
    LaneAggregate,
    RetrievalLane,
    _FrozenContract,
)

RRF_K: Final = 60
RELEASE_POOL_SIZES: Final = frozenset({8, 12, 16, 20})
DIAGNOSTIC_POOL_SIZE: Final = 50


class RankingRejectionCode(StrEnum):
    DUPLICATE_CHUNK = "DUPLICATE_CHUNK"
    DOCUMENT_VERSION_COLLAPSE = "DOCUMENT_VERSION_COLLAPSE"
    LANE_POOL_CUTOFF = "LANE_POOL_CUTOFF"
    FUSION_POOL_CUTOFF = "FUSION_POOL_CUTOFF"
    INELIGIBLE = "INELIGIBLE"


class RankingRejectionCount(_FrozenContract):
    code: RankingRejectionCode
    count: int = Field(ge=0)


class CollapseDiagnostics(_FrozenContract):
    """Content-free counts for a lane collapse or chunk merge."""

    input_chunk_count: int = Field(ge=0)
    eligible_chunk_count: int = Field(ge=0)
    distinct_version_count: int = Field(ge=0)
    duplicates_collapsed: int = Field(ge=0)
    pool_cutoff_count: int = Field(ge=0)
    rejection_counts: tuple[RankingRejectionCount, ...] = Field(default=())

    @model_validator(mode="after")
    def validate_rejection_codes(self) -> "CollapseDiagnostics":
        if len({item.code for item in self.rejection_counts}) != len(self.rejection_counts):
            raise ValueError("rejection counts must be unique per code")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class ChunkMergeResult(_FrozenContract):
    candidates: tuple[CandidateEvidence, ...] = Field(exclude=True, repr=False)
    diagnostics: CollapseDiagnostics

    def to_public_dict(self) -> dict[str, object]:
        return {
            "merged_candidate_count": len(self.candidates),
            "diagnostics": self.diagnostics.to_public_dict(),
        }


class LaneDocumentPool(_FrozenContract):
    lane: RetrievalLane
    pool_size: int = Field(ge=1, le=50)
    candidates: tuple[CollapsedDocumentCandidate, ...] = Field(exclude=True, repr=False)
    diagnostics: CollapseDiagnostics

    def to_public_dict(self) -> dict[str, object]:
        return {
            "lane": self.lane.value,
            "pool_size": self.pool_size,
            "candidate_count": len(self.candidates),
            "diagnostics": self.diagnostics.to_public_dict(),
        }


class LaneUniqueContribution(_FrozenContract):
    lane: RetrievalLane
    unique_count: int = Field(ge=0)
    document_version_ids: tuple[UUID, ...] = Field(default=(), exclude=True, repr=False)

    @model_validator(mode="after")
    def validate_count(self) -> "LaneUniqueContribution":
        if self.unique_count != len(self.document_version_ids):
            raise ValueError("unique_count must equal document_version_ids length")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {"lane": self.lane.value, "unique_count": self.unique_count}


class FusedPool(_FrozenContract):
    pool_size: int = Field(ge=1, le=20)
    candidates: tuple[CollapsedDocumentCandidate, ...] = Field(exclude=True, repr=False)
    rejection_counts: tuple[RankingRejectionCount, ...] = Field(default=())
    lane_unique_contributions: tuple[LaneUniqueContribution, ...] = Field(default=())

    @model_validator(mode="after")
    def validate_counts(self) -> "FusedPool":
        if len({candidate.identity.document_version_id for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("fused candidates must have unique document versions")
        if len({item.code for item in self.rejection_counts}) != len(self.rejection_counts):
            raise ValueError("rejection counts must be unique per code")
        if len({item.lane for item in self.lane_unique_contributions}) != len(
            self.lane_unique_contributions
        ):
            raise ValueError("lane contribution metrics must be unique per lane")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "pool_size": self.pool_size,
            "candidate_count": len(self.candidates),
            "rejection_counts": [item.model_dump(mode="json") for item in self.rejection_counts],
            "lane_unique_contributions": [
                item.to_public_dict() for item in self.lane_unique_contributions
            ],
        }


class DiagnosticFusedPool(_FrozenContract):
    """Top-50 recall diagnostic only; it cannot be used for release evidence selection."""

    pool_size: Literal[50] = 50
    release_eligible: Literal[False] = False
    candidates: tuple[CollapsedDocumentCandidate, ...] = Field(exclude=True, repr=False)
    rejection_counts: tuple[RankingRejectionCount, ...] = Field(default=())

    @model_validator(mode="after")
    def validate_candidates(self) -> "DiagnosticFusedPool":
        if len(self.candidates) > self.pool_size:
            raise ValueError("diagnostic fused pool cannot exceed top 50")
        if len({candidate.identity.document_version_id for candidate in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("diagnostic fused candidates must have unique document versions")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "pool_size": self.pool_size,
            "release_eligible": self.release_eligible,
            "candidate_count": len(self.candidates),
            "rejection_counts": [item.model_dump(mode="json") for item in self.rejection_counts],
        }


class PoolMeasurementSummary(_FrozenContract):
    """Generic evaluator-provided aggregate, deliberately without identities or text."""

    pool_size: Literal[8, 12, 16, 20]
    candidate_identity_count: int = Field(ge=0)
    nonexpected_candidate_rate: float = Field(ge=0, le=1)
    p95_latency_ms: float = Field(ge=0)
    query_count: int = Field(ge=0)
    set_c_failure_count: int = Field(ge=0)

    @field_validator("nonexpected_candidate_rate", "p95_latency_ms")
    @classmethod
    def validate_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("measurements must be finite")
        return value


class PoolReferenceSummary(_FrozenContract):
    """Frozen, content-free prior measurement used only to evaluate pool 8."""

    candidate_identity_count: int = Field(ge=0)
    nonexpected_candidate_rate: float = Field(ge=0, le=1)
    p95_latency_ms: float = Field(ge=0)
    query_count: int = Field(ge=0)
    set_c_failure_count: int = Field(ge=0)

    @field_validator("nonexpected_candidate_rate", "p95_latency_ms")
    @classmethod
    def validate_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("measurements must be finite")
        return value

    def to_public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


class PoolSelectionStatus(StrEnum):
    SELECTED = "SELECTED"
    NO_SELECTION = "NO_SELECTION"


class ParetoPoolSelection(_FrozenContract):
    status: PoolSelectionStatus
    selected_pool_size: Literal[8, 12, 16, 20] | None = None
    eligible_pool_sizes: tuple[Literal[8, 12, 16, 20], ...] = Field(default=())

    @model_validator(mode="after")
    def validate_status(self) -> "ParetoPoolSelection":
        if self.status is PoolSelectionStatus.SELECTED:
            if (
                self.selected_pool_size is None
                or self.selected_pool_size not in self.eligible_pool_sizes
            ):
                raise ValueError("a selected pool must be eligible")
        elif self.selected_pool_size is not None or self.eligible_pool_sizes:
            raise ValueError("NO_SELECTION cannot expose selected or eligible pools")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


def _counts(**values: int) -> tuple[RankingRejectionCount, ...]:
    return tuple(
        RankingRejectionCount(code=RankingRejectionCode(code), count=count)
        for code, count in values.items()
        if count
    )


def _validate_lane_pool_size(pool_size: int, *, allow_diagnostic: bool) -> None:
    allowed = RELEASE_POOL_SIZES | ({DIAGNOSTIC_POOL_SIZE} if allow_diagnostic else set())
    if pool_size not in allowed:
        raise ValueError("pool_size must be a release pool or the diagnostic top-50 pool")


def _candidate_observation(candidate: CandidateEvidence, lane: RetrievalLane):
    for observation in candidate.observations:
        if observation.lane is lane:
            return observation
    raise ValueError("candidate does not contain the requested lane observation")


def _merge_units(candidates: Iterable[CandidateEvidence]) -> tuple[str, ...]:
    return tuple(sorted({unit_id for candidate in candidates for unit_id in candidate.unit_ids}))


def _score_sort_key(candidate: CandidateEvidence, lane: RetrievalLane, comparable: bool) -> float:
    score = _candidate_observation(candidate, lane).score
    return -score if comparable and score is not None else 0.0


def _merged_supporting_semantic_score(candidates: Iterable[CandidateEvidence]) -> float | None:
    scores = [
        candidate.supporting_semantic_score
        for candidate in candidates
        if candidate.supporting_semantic_score is not None
    ]
    if not scores:
        return None
    first = scores[0]
    if any(not isclose(first, score, rel_tol=0.0, abs_tol=1e-9) for score in scores[1:]):
        raise ValueError("same chunk cannot contain conflicting supporting semantic scores")
    return first


def merge_chunk_candidates(candidates: Iterable[CandidateEvidence]) -> ChunkMergeResult:
    """Merge independent lane observations for the same fully matching child chunk."""

    grouped: dict[UUID, list[CandidateEvidence]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.chunk_id].append(candidate)
    merged: list[CandidateEvidence] = []
    duplicate_count = 0
    for chunk_id in sorted(grouped, key=str):
        group = grouped[chunk_id]
        first = group[0]
        if any(
            candidate.identity != first.identity
            or candidate.ordinal != first.ordinal
            or candidate.eligible != first.eligible
            or candidate.rejection_code != first.rejection_code
            or candidate.source_scope != first.source_scope
            for candidate in group[1:]
        ):
            raise ValueError("same chunk candidates must fully agree outside lane observations")
        observations = [
            observation for candidate in group for observation in candidate.observations
        ]
        lane_observations = {}
        for observation in observations:
            existing = lane_observations.get(observation.lane)
            if existing is not None and existing != observation:
                raise ValueError("same chunk cannot contain conflicting observations for one lane")
            lane_observations[observation.lane] = observation
        duplicate_count += len(group) - 1
        merged.append(
            CandidateEvidence(
                chunk_id=chunk_id,
                identity=first.identity,
                ordinal=first.ordinal,
                observations=tuple(lane_observations[lane] for lane in sorted(lane_observations)),
                unit_ids=_merge_units(group),
                supporting_semantic_score=_merged_supporting_semantic_score(group),
                source_scope=first.source_scope,
                eligible=first.eligible,
                rejection_code=first.rejection_code,
            )
        )
    eligible_count = sum(candidate.eligible for candidate in merged)
    diagnostics = CollapseDiagnostics(
        input_chunk_count=sum(len(group) for group in grouped.values()),
        eligible_chunk_count=eligible_count,
        distinct_version_count=len(
            {candidate.identity.document_version_id for candidate in merged}
        ),
        duplicates_collapsed=duplicate_count,
        pool_cutoff_count=0,
        rejection_counts=_counts(
            DUPLICATE_CHUNK=duplicate_count,
            INELIGIBLE=len(merged) - eligible_count,
        ),
    )
    return ChunkMergeResult(candidates=tuple(merged), diagnostics=diagnostics)


def _validate_version_identity(
    candidates: Iterable[CandidateEvidence | CollapsedDocumentCandidate],
) -> None:
    identities: dict[UUID, DocumentIdentity] = {}
    for candidate in candidates:
        identity = candidate.identity
        previous = identities.get(identity.document_version_id)
        if previous is not None and previous != identity:
            raise ValueError("one document version cannot be merged across different identities")
        identities[identity.document_version_id] = identity


def build_lane_document_pool(
    candidates: Iterable[CandidateEvidence], lane: RetrievalLane, pool_size: int
) -> LaneDocumentPool:
    """Collapse all raw lane chunks before applying a release or diagnostic pool cutoff."""

    _validate_lane_pool_size(pool_size, allow_diagnostic=True)
    lane_candidates = tuple(candidate for candidate in candidates if any(
        observation.lane is lane for observation in candidate.observations
    ))
    _validate_version_identity(lane_candidates)
    eligible = tuple(candidate for candidate in lane_candidates if candidate.eligible)
    groups: dict[DocumentIdentity, list[CandidateEvidence]] = defaultdict(list)
    for candidate in eligible:
        groups[candidate.identity].append(candidate)
    collapsed: list[CollapsedDocumentCandidate] = []
    for identity, group in groups.items():
        comparable_scores = all(
            _candidate_observation(candidate, lane).score is not None for candidate in group
        )
        representative = min(
            group,
            key=lambda candidate: (
                _candidate_observation(candidate, lane).rank,
                _score_sort_key(candidate, lane, comparable_scores),
                candidate.ordinal,
                str(candidate.chunk_id),
            ),
        )
        observation = _candidate_observation(representative, lane)
        collapsed.append(
            CollapsedDocumentCandidate(
                identity=identity,
                representative=representative,
                supporting_chunk_count=len(group) - 1,
                best_chunk_rank=observation.rank,
                best_chunk_score=observation.score,
                lane_aggregates=(
                    LaneAggregate(
                        lane=lane,
                        best_rank=observation.rank,
                        best_score=observation.score,
                    ),
                ),
                merged_unit_ids=_merge_units(group),
            )
        )
    ordered = sorted(
        collapsed,
        key=lambda candidate: (
            candidate.best_chunk_rank if candidate.best_chunk_rank is not None else 51,
            -candidate.best_chunk_score if candidate.best_chunk_score is not None else 0,
            candidate.representative.ordinal,
            str(candidate.representative.chunk_id),
        ),
    )
    selected = tuple(ordered[:pool_size])
    cutoff = len(ordered) - len(selected)
    diagnostics = CollapseDiagnostics(
        input_chunk_count=len(lane_candidates),
        eligible_chunk_count=len(eligible),
        distinct_version_count=len(groups),
        duplicates_collapsed=len(eligible) - len(groups),
        pool_cutoff_count=cutoff,
        rejection_counts=_counts(
            DOCUMENT_VERSION_COLLAPSE=len(eligible) - len(groups),
            LANE_POOL_CUTOFF=cutoff,
            INELIGIBLE=len(lane_candidates) - len(eligible),
        ),
    )
    return LaneDocumentPool(
        lane=lane,
        pool_size=pool_size,
        candidates=selected,
        diagnostics=diagnostics,
    )


def _lane_aggregate(candidate: CollapsedDocumentCandidate, lane: RetrievalLane) -> LaneAggregate:
    aggregates = [aggregate for aggregate in candidate.lane_aggregates if aggregate.lane is lane]
    if len(aggregates) != 1:
        raise ValueError(
            "collapsed lane candidate must contain exactly one aggregate for its pool lane"
        )
    return aggregates[0]


def _representative_key(
    entry: tuple[RetrievalLane, CollapsedDocumentCandidate]
) -> tuple[int, str, int, str]:
    lane, candidate = entry
    aggregate = _lane_aggregate(candidate, lane)
    return (
        aggregate.best_rank or 51,
        lane.value,
        candidate.representative.ordinal,
        str(candidate.representative.chunk_id),
    )


def _fuse_documents(
    collapsed_lane_pools: Iterable[LaneDocumentPool],
) -> tuple[CollapsedDocumentCandidate, ...]:
    """Fuse all lane-pool versions before a release or diagnostic cutoff is applied."""

    pools = tuple(collapsed_lane_pools)
    if len({pool.lane for pool in pools}) != len(pools):
        raise ValueError("only one collapsed pool is allowed per lane")
    all_candidates = [candidate for pool in pools for candidate in pool.candidates]
    _validate_version_identity(all_candidates)
    grouped: dict[DocumentIdentity, list[tuple[RetrievalLane, CollapsedDocumentCandidate]]] = (
        defaultdict(list)
    )
    for pool in pools:
        for candidate in pool.candidates:
            grouped[candidate.identity].append((pool.lane, candidate))
    fused: list[CollapsedDocumentCandidate] = []
    for identity, entries in grouped.items():
        if len({lane for lane, _ in entries}) != len(entries):
            raise ValueError("a document version cannot appear twice in one lane pool")
        lane_aggregates = tuple(
            sorted(
                (_lane_aggregate(candidate, lane) for lane, candidate in entries),
                key=lambda item: item.lane.value,
            )
        )
        fusion_score = sum(
            1.0 / (RRF_K + (aggregate.best_rank or 51)) for aggregate in lane_aggregates
        )
        _, representative = min(entries, key=_representative_key)
        best_aggregate = min(
            lane_aggregates,
            key=lambda item: (item.best_rank or 51, item.lane.value),
        )
        fused.append(
            CollapsedDocumentCandidate(
                identity=identity,
                representative=representative.representative,
                supporting_chunk_count=max(
                    candidate.supporting_chunk_count for _, candidate in entries
                ),
                best_chunk_rank=best_aggregate.best_rank,
                best_chunk_score=best_aggregate.best_score,
                lane_aggregates=lane_aggregates,
                merged_unit_ids=_merge_units(candidate.representative for _, candidate in entries),
                fusion_score=fusion_score,
            )
        )
    ordered = sorted(
        fused,
        key=lambda candidate: (
            -(candidate.fusion_score or 0),
            candidate.best_chunk_rank or 51,
            candidate.representative.ordinal,
            str(candidate.representative.chunk_id),
            str(candidate.identity.document_version_id),
        ),
    )
    return tuple(ordered)


def fused_pool(collapsed_lane_pools: Iterable[LaneDocumentPool], pool_size: int) -> FusedPool:
    """Fuse distinct document versions with equal-weight RRF; no lane has priority."""

    _validate_lane_pool_size(pool_size, allow_diagnostic=False)
    ordered = _fuse_documents(collapsed_lane_pools)
    selected = ordered[:pool_size]
    cutoff = len(ordered) - len(selected)
    return FusedPool(
        pool_size=pool_size,
        candidates=selected,
        rejection_counts=_counts(FUSION_POOL_CUTOFF=cutoff),
    )


def fused_diagnostic_top50(collapsed_lane_pools: Iterable[LaneDocumentPool]) -> DiagnosticFusedPool:
    """Return a non-release, equal-RRF top-50 diagnostic pool for recall measurement only."""

    ordered = _fuse_documents(collapsed_lane_pools)
    selected = ordered[:DIAGNOSTIC_POOL_SIZE]
    cutoff = len(ordered) - len(selected)
    return DiagnosticFusedPool(
        candidates=selected,
        rejection_counts=_counts(FUSION_POOL_CUTOFF=cutoff),
    )


def select_final_top3(pool: FusedPool) -> tuple[CollapsedDocumentCandidate, ...]:
    """Return at most three existing evidence records; this helper never pads."""

    if not isinstance(pool, FusedPool):
        raise TypeError("final evidence selection requires a release FusedPool")
    return pool.candidates[:3]


def lane_unique_contributions(
    collapsed_lane_pools: Iterable[LaneDocumentPool], pool_size: int
) -> tuple[LaneUniqueContribution, ...]:
    """Count fused documents lost under deterministic one-lane counterfactual removal."""

    pools = tuple(collapsed_lane_pools)
    full = fused_pool(pools, pool_size)
    full_ids = {candidate.identity.document_version_id for candidate in full.candidates}
    contributions: list[LaneUniqueContribution] = []
    for pool in sorted(pools, key=lambda item: item.lane.value):
        without_lane = fused_pool(
            (item for item in pools if item.lane is not pool.lane), pool_size
        )
        remaining_ids = {
            candidate.identity.document_version_id for candidate in without_lane.candidates
        }
        unique_ids = tuple(sorted(full_ids - remaining_ids, key=str))
        contributions.append(
            LaneUniqueContribution(
                lane=pool.lane,
                unique_count=len(unique_ids),
                document_version_ids=unique_ids,
            )
        )
    return tuple(contributions)


def with_lane_unique_contributions(
    collapsed_lane_pools: Iterable[LaneDocumentPool], pool_size: int
) -> FusedPool:
    """Attach count-only lane counterfactuals to an otherwise unchanged fused pool."""

    pools = tuple(collapsed_lane_pools)
    fused = fused_pool(pools, pool_size)
    return fused.model_copy(
        update={"lane_unique_contributions": lane_unique_contributions(pools, pool_size)}
    )


def select_pareto_pool(
    reference: PoolReferenceSummary, measurements: Iterable[PoolMeasurementSummary]
) -> ParetoPoolSelection:
    """Evaluate pool 8 against its reference, then each later pool against its predecessor."""

    ordered = tuple(sorted(measurements, key=lambda item: item.pool_size))
    if tuple(item.pool_size for item in ordered) != (8, 12, 16, 20):
        raise ValueError("measurements must contain exactly the four frozen pool sizes")
    eligible: list[Literal[8, 12, 16, 20]] = []
    prior: PoolReferenceSummary | PoolMeasurementSummary = reference
    for current in ordered:
        gain_or_latency = (
            current.candidate_identity_count >= prior.candidate_identity_count + 1
            or (
                current.candidate_identity_count == prior.candidate_identity_count
                and current.p95_latency_ms < prior.p95_latency_ms
            )
        )
        safe_cost = (
            current.nonexpected_candidate_rate <= prior.nonexpected_candidate_rate + 0.02
            and current.p95_latency_ms <= 2450
            and current.query_count <= 12
            and current.set_c_failure_count == 0
        )
        if gain_or_latency and safe_cost:
            eligible.append(current.pool_size)
        prior = current
    if not eligible:
        return ParetoPoolSelection(status=PoolSelectionStatus.NO_SELECTION)
    return ParetoPoolSelection(
        status=PoolSelectionStatus.SELECTED,
        selected_pool_size=min(eligible),
        eligible_pool_sizes=tuple(eligible),
    )
