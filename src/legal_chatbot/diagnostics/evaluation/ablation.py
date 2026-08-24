"""Typed, answer-free ablation records for C01 through C08."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AblationProfile(StrEnum):
    C01 = "C01"
    C02 = "C02"
    C03 = "C03"
    C04 = "C04"
    C05 = "C05"
    C06 = "C06"
    C07 = "C07"
    C08 = "C08"


class EvaluationMeasurementState(StrEnum):
    MEASURED = "MEASURED"
    NOT_MEASURED = "NOT_MEASURED"


class AblationMeasurement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: AblationProfile
    state: EvaluationMeasurementState
    set_a_average: float | None = Field(default=None, ge=0, le=10)
    set_a_pass_count: int | None = Field(default=None, ge=0, le=10)
    set_b_regression_count: int | None = Field(default=None, ge=0)
    set_c_safety_failure_count: int | None = Field(default=None, ge=0)
    citation_provenance_clean: bool | None = None
    benchmark_leakage_found: bool | None = None

    @model_validator(mode="after")
    def validate_measurement_state(self) -> AblationMeasurement:
        values = (
            self.set_a_average,
            self.set_a_pass_count,
            self.set_b_regression_count,
            self.set_c_safety_failure_count,
            self.citation_provenance_clean,
            self.benchmark_leakage_found,
        )
        if self.state is EvaluationMeasurementState.MEASURED and any(
            value is None for value in values
        ):
            raise ValueError("measured ablation requires every aggregate")
        if self.state is EvaluationMeasurementState.NOT_MEASURED and any(
            value is not None for value in values
        ):
            raise ValueError("unmeasured ablation cannot claim an aggregate")
        return self


class AblationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    measurements: tuple[AblationMeasurement, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_profiles(self) -> AblationReport:
        if len({measurement.profile for measurement in self.measurements}) != len(
            self.measurements
        ):
            raise ValueError("ablation profiles must be unique")
        return self
