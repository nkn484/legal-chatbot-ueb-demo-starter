"""Named immutable Phase-A strategy families, with no runtime integration."""

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from pydantic import Field, field_validator, model_validator

from .models import RetrievalLane, _FrozenContract

RRF_CONSTANT: Final = 60
ALLOWED_CANDIDATE_POOLS: Final = frozenset({8, 12, 16, 20})
QUALITY_STRATEGY_VERSION: Final = "quality-retrieval-a1-v1"
ENVIRONMENT_FLAGS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "quality_repair_enabled": "RETRIEVAL_QUALITY_REPAIR_ENABLED",
        "quality_title_search_enabled": "RETRIEVAL_QUALITY_TITLE_SEARCH_ENABLED",
        "quality_hybrid_fusion_enabled": "RETRIEVAL_QUALITY_HYBRID_FUSION_ENABLED",
        "quality_query_planner_enabled": "RETRIEVAL_QUALITY_QUERY_PLANNER_ENABLED",
        "quality_dynamic_evidence_enabled": "RETRIEVAL_QUALITY_DYNAMIC_EVIDENCE_ENABLED",
        "quality_repair_retrieval_enabled": "RETRIEVAL_QUALITY_REPAIR_RETRIEVAL_ENABLED",
    }
)
ENVIRONMENT_FLAG_CAPABILITIES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "quality_repair_enabled": "quality_repair_enabled",
        "quality_title_search_enabled": "title_search_enabled",
        "quality_hybrid_fusion_enabled": "hybrid_fusion_enabled",
        "quality_query_planner_enabled": "deterministic_analyzer_enabled",
        "quality_dynamic_evidence_enabled": "dynamic_evidence_enabled",
        "quality_repair_retrieval_enabled": "repair_retrieval_enabled",
    }
)


class EvidencePaddingPolicy(StrEnum):
    NO_PADDING = "NO_PADDING"


class CandidatePoolSelectionMode(StrEnum):
    FIXED = "FIXED"
    PARETO_MATRIX = "PARETO_MATRIX"
    POOL_SELECTED_FROM_HYBRID = "POOL_SELECTED_FROM_HYBRID"


class QualityRepairStrategy(_FrozenContract):
    """A quality-family hypothesis requiring a pool only when materialized later."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    strategy_version: Literal["quality-retrieval-a1-v1"] = QUALITY_STRATEGY_VERSION
    candidate_pool_sizes: tuple[Literal[8, 12, 16, 20], ...] = Field(min_length=1, max_length=4)
    candidate_pool_selection_mode: CandidatePoolSelectionMode
    enabled_lanes: tuple[RetrievalLane, ...] = Field(min_length=1, max_length=3)
    quality_repair_enabled: Literal[True] = True
    collapse_documents: Literal[True] = True
    title_search_enabled: bool = False
    hybrid_fusion_enabled: bool = False
    deterministic_analyzer_enabled: bool = False
    protection_enabled: bool = False
    dynamic_evidence_enabled: bool = False
    reranker_enabled: bool = False
    repair_retrieval_enabled: bool = False
    final_evidence_min: Literal[3] = 3
    final_evidence_max: Literal[3, 6] = 3
    evidence_padding_policy: Literal[EvidencePaddingPolicy.NO_PADDING] = (
        EvidencePaddingPolicy.NO_PADDING
    )
    max_sub_intents: Literal[4] = 4
    repair_rounds: Literal[0, 1] = 0
    rrf_constant: Literal[60] = RRF_CONSTANT
    lane_weights: tuple[float, ...]

    @field_validator("lane_weights")
    @classmethod
    def validate_fixed_equal_weights(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(weight != 1.0 for weight in value):
            raise ValueError("Phase A lane weights are fixed and equal at 1.0")
        return value

    @model_validator(mode="after")
    def validate_strategy_family(self) -> "QualityRepairStrategy":
        if len(set(self.candidate_pool_sizes)) != len(self.candidate_pool_sizes):
            raise ValueError("candidate_pool_sizes must be unique")
        if len(set(self.enabled_lanes)) != len(self.enabled_lanes):
            raise ValueError("enabled_lanes must be unique")
        if len(self.lane_weights) != len(self.enabled_lanes):
            raise ValueError("lane_weights must cover every enabled lane")
        if self.candidate_pool_selection_mode is CandidatePoolSelectionMode.FIXED:
            if len(self.candidate_pool_sizes) != 1:
                raise ValueError("a fixed family must declare exactly one candidate pool")
        elif set(self.candidate_pool_sizes) != ALLOWED_CANDIDATE_POOLS:
            raise ValueError("matrix families must retain the 8/12/16/20 pool matrix")
        if self.title_search_enabled != (RetrievalLane.TITLE_FTS in self.enabled_lanes):
            raise ValueError("title_search_enabled must match the title lane")
        if self.hybrid_fusion_enabled != (len(self.enabled_lanes) > 1):
            raise ValueError("hybrid_fusion_enabled must match multi-lane retrieval")
        if self.repair_retrieval_enabled != (self.repair_rounds == 1):
            raise ValueError("repair retrieval and repair rounds must agree")
        expected_evidence_max = 6 if self.dynamic_evidence_enabled else 3
        if self.final_evidence_max != expected_evidence_max:
            raise ValueError("dynamic evidence determines the final evidence bounds")
        return self

    @property
    def capabilities(self) -> Mapping[str, bool]:
        """Nine internal capabilities; only five are configurable subflags."""

        return MappingProxyType(
            {
                "quality_repair_enabled": self.quality_repair_enabled,
                "document_collapse_enabled": self.collapse_documents,
                "title_search_enabled": self.title_search_enabled,
                "hybrid_fusion_enabled": self.hybrid_fusion_enabled,
                "deterministic_analyzer_enabled": self.deterministic_analyzer_enabled,
                "protected_opportunity_enabled": self.protection_enabled,
                "dynamic_evidence_enabled": self.dynamic_evidence_enabled,
                "reranker_enabled": self.reranker_enabled,
                "repair_retrieval_enabled": self.repair_retrieval_enabled,
            }
        )

    @property
    def required_quality_flags(self) -> frozenset[str]:
        """Required environment subflags, excluding internal-only capabilities."""

        return frozenset(
            environment_name
            for environment_name, capability_name in ENVIRONMENT_FLAG_CAPABILITIES.items()
            if environment_name != "quality_repair_enabled" and self.capabilities[capability_name]
        )


class QualityAblationControl(_FrozenContract):
    """Non-quality control retained in the same authoritative ablation registry."""

    name: Literal["quality_retrieval_current_default_v1"]
    strategy_version: Literal["quality-retrieval-a1-v1"] = QUALITY_STRATEGY_VERSION
    release_control: Literal[True] = True
    candidate_pool_size: Literal[3] = 3
    final_evidence_min: Literal[3] = 3
    final_evidence_max: Literal[3] = 3


class MaterializedQualityRepairStrategy(_FrozenContract):
    """A future executable shape with exactly one pool selected after Gate B."""

    profile_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    strategy_version: Literal["quality-retrieval-a1-v1"] = QUALITY_STRATEGY_VERSION
    selected_pool: Literal[8, 12, 16, 20]
    family: QualityRepairStrategy = Field(repr=False)

    @model_validator(mode="after")
    def validate_materialization(self) -> "MaterializedQualityRepairStrategy":
        if self.profile_name != self.family.name:
            raise ValueError("profile_name must match the materialized family")
        if self.selected_pool not in self.family.candidate_pool_sizes:
            raise ValueError("selected_pool must be declared by the strategy family")
        return self


type QualityAblationProfile = QualityRepairStrategy | QualityAblationControl


def _family(
    name: str,
    mode: CandidatePoolSelectionMode,
    pools: tuple[int, ...],
    lanes: tuple[RetrievalLane, ...],
    **features: object,
) -> QualityRepairStrategy:
    values: dict[str, object] = {
        "name": name,
        "candidate_pool_selection_mode": mode,
        "candidate_pool_sizes": pools,
        "enabled_lanes": lanes,
        "title_search_enabled": RetrievalLane.TITLE_FTS in lanes,
        "hybrid_fusion_enabled": len(lanes) > 1,
        "lane_weights": (1.0,) * len(lanes),
    }
    values.update(features)
    return QualityRepairStrategy.model_validate(values)


_SEMANTIC = (RetrievalLane.SEMANTIC,)
_HYBRID = (RetrievalLane.SEMANTIC, RetrievalLane.CONTENT_FTS, RetrievalLane.TITLE_FTS)
_POOL_MATRIX = (8, 12, 16, 20)

QUALITY_REPAIR_PROFILES: Final[Mapping[str, QualityAblationProfile]] = MappingProxyType(
    {
        "quality_retrieval_current_default_v1": QualityAblationControl(
            name="quality_retrieval_current_default_v1"
        ),
        "quality_retrieval_document_collapse_v1": _family(
            "quality_retrieval_document_collapse_v1",
            CandidatePoolSelectionMode.FIXED,
            (8,),
            _SEMANTIC,
        ),
        "quality_retrieval_hybrid_v1": _family(
            "quality_retrieval_hybrid_v1",
            CandidatePoolSelectionMode.PARETO_MATRIX,
            _POOL_MATRIX,
            _HYBRID,
        ),
        "quality_retrieval_analyzer_protected_v1": _family(
            "quality_retrieval_analyzer_protected_v1",
            CandidatePoolSelectionMode.POOL_SELECTED_FROM_HYBRID,
            _POOL_MATRIX,
            _HYBRID,
            deterministic_analyzer_enabled=True,
            protection_enabled=True,
        ),
        "quality_retrieval_dynamic_evidence_v1": _family(
            "quality_retrieval_dynamic_evidence_v1",
            CandidatePoolSelectionMode.POOL_SELECTED_FROM_HYBRID,
            _POOL_MATRIX,
            _HYBRID,
            deterministic_analyzer_enabled=True,
            protection_enabled=True,
            dynamic_evidence_enabled=True,
            final_evidence_max=6,
        ),
        "quality_retrieval_reranker_v1": _family(
            "quality_retrieval_reranker_v1",
            CandidatePoolSelectionMode.POOL_SELECTED_FROM_HYBRID,
            _POOL_MATRIX,
            _HYBRID,
            deterministic_analyzer_enabled=True,
            protection_enabled=True,
            dynamic_evidence_enabled=True,
            reranker_enabled=True,
            final_evidence_max=6,
        ),
        "quality_retrieval_evidence_repair_v1": _family(
            "quality_retrieval_evidence_repair_v1",
            CandidatePoolSelectionMode.POOL_SELECTED_FROM_HYBRID,
            _POOL_MATRIX,
            _HYBRID,
            deterministic_analyzer_enabled=True,
            protection_enabled=True,
            dynamic_evidence_enabled=True,
            repair_retrieval_enabled=True,
            repair_rounds=1,
            final_evidence_max=6,
        ),
        "quality_retrieval_full_candidate_v1": _family(
            "quality_retrieval_full_candidate_v1",
            CandidatePoolSelectionMode.POOL_SELECTED_FROM_HYBRID,
            _POOL_MATRIX,
            _HYBRID,
            deterministic_analyzer_enabled=True,
            protection_enabled=True,
            dynamic_evidence_enabled=True,
            reranker_enabled=True,
            repair_retrieval_enabled=True,
            repair_rounds=1,
            final_evidence_max=6,
        ),
    }
)
QUALITY_ABLATION_PROFILES: Final[Mapping[str, QualityAblationProfile]] = QUALITY_REPAIR_PROFILES
QUALITY_PROFILE_NAMES: Final[tuple[str, ...]] = tuple(QUALITY_REPAIR_PROFILES)


def materialize_strategy(
    profile_name: str, selected_pool: Literal[8, 12, 16, 20]
) -> MaterializedQualityRepairStrategy:
    """Materialize one declared quality family; controls are intentionally ineligible."""

    profile = QUALITY_REPAIR_PROFILES.get(profile_name)
    if not isinstance(profile, QualityRepairStrategy):
        raise ValueError("profile_name must identify a materializable quality strategy")
    return MaterializedQualityRepairStrategy(
        profile_name=profile_name,
        selected_pool=selected_pool,
        family=profile,
    )


M2_NEGATIVE_COMPARATOR: Final[Mapping[str, str | bool]] = MappingProxyType(
    {
        "name": "m2",
        "included_in_phase_a_profiles": False,
        "role": "negative_comparator_only",
    }
)
