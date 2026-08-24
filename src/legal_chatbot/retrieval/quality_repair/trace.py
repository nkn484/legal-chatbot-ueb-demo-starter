"""Content-free Phase-A diagnostics and cost accounting contracts."""

from math import isfinite

from pydantic import Field, field_validator, model_validator

from .analyzer import AnalyzerObservation
from .models import RetrievalLane, _FrozenContract
from .strategy import QUALITY_PROFILE_NAMES, QUALITY_STRATEGY_VERSION


class BufferSummary(_FrozenContract):
    """Numeric database buffer summary without SQL or identifiers."""

    shared_hit: int = Field(default=0, ge=0)
    shared_read: int = Field(default=0, ge=0)
    temp_read: int = Field(default=0, ge=0)
    temp_written: int = Field(default=0, ge=0)


class LaneMetrics(_FrozenContract):
    lane: RetrievalLane
    query_count: int = Field(ge=0, le=50)
    elapsed_ms: float = Field(ge=0)
    sql_elapsed_ms: float = Field(ge=0)
    rows_returned: int = Field(ge=0, le=50)
    buffers: BufferSummary = Field(default_factory=BufferSummary)

    @field_validator("elapsed_ms", "sql_elapsed_ms")
    @classmethod
    def validate_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("timings must be finite")
        return value


class RejectionCount(_FrozenContract):
    code: str = Field(min_length=1, max_length=64)
    count: int = Field(ge=0)


class QualityRepairCost(_FrozenContract):
    analyzer_elapsed_ms: float = Field(default=0, ge=0)
    fusion_elapsed_ms: float = Field(default=0, ge=0)
    reranker_elapsed_ms: float = Field(default=0, ge=0)
    repair_elapsed_ms: float = Field(default=0, ge=0)
    sql_elapsed_ms: float = Field(default=0, ge=0)
    query_count: int = Field(default=0, ge=0, le=50)

    @field_validator(
        "analyzer_elapsed_ms",
        "fusion_elapsed_ms",
        "reranker_elapsed_ms",
        "repair_elapsed_ms",
        "sql_elapsed_ms",
    )
    @classmethod
    def validate_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("timings must be finite")
        return value


class QualityRepairMetrics(_FrozenContract):
    input_candidate_count: int = Field(ge=0)
    collapsed_candidate_count: int = Field(ge=0)
    eligible_candidate_count: int = Field(ge=0)
    final_evidence_count: int = Field(ge=0, le=6)
    promotion_count: int = Field(default=0, ge=0)
    demotion_count: int = Field(default=0, ge=0)
    rejections: tuple[RejectionCount, ...] = Field(default=())
    lane_metrics: tuple[LaneMetrics, ...] = Field(default=())
    cost: QualityRepairCost = Field(default_factory=QualityRepairCost)

    @model_validator(mode="after")
    def validate_summary(self) -> "QualityRepairMetrics":
        if self.collapsed_candidate_count > self.input_candidate_count:
            raise ValueError("collapsed candidates cannot exceed input candidates")
        if self.eligible_candidate_count > self.collapsed_candidate_count:
            raise ValueError("eligible candidates cannot exceed collapsed candidates")
        if self.final_evidence_count > self.eligible_candidate_count:
            raise ValueError("final evidence cannot exceed eligible candidates")
        if len({rejection.code for rejection in self.rejections}) != len(self.rejections):
            raise ValueError("rejection codes must be unique")
        if len({metric.lane for metric in self.lane_metrics}) != len(self.lane_metrics):
            raise ValueError("lane metrics must be unique")
        return self


class QualityRepairTrace(_FrozenContract):
    """Safe trace schema with a memory-only repair query excluded from diagnostics."""

    strategy_name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    strategy_version: str = Field(pattern=r"^[a-z][a-z0-9._-]{0,63}$")
    analyzer: AnalyzerObservation | None = None
    repair_query_text: str | None = Field(default=None, max_length=4_000, exclude=True, repr=False)
    metrics: QualityRepairMetrics

    @model_validator(mode="after")
    def validate_profile_reference(self) -> "QualityRepairTrace":
        if self.strategy_name not in QUALITY_PROFILE_NAMES:
            raise ValueError("strategy_name must be an authoritative quality profile name")
        if self.strategy_version != QUALITY_STRATEGY_VERSION:
            raise ValueError("strategy_version must match the authoritative profile version")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "analyzer": None if self.analyzer is None else self.analyzer.to_public_dict(),
            "metrics": self.metrics.model_dump(mode="json"),
        }
