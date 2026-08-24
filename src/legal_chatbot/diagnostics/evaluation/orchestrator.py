"""Pure, evaluation-only planning over bounded analyzer observations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from legal_chatbot.retrieval.quality_repair.analyzer import (
    AnalyzerObservation,
    AnalyzerPolicy,
    AnalyzerUnit,
    ConceptQuery,
    LegalQuestionAnalyzer,
    SourceAccessStatus,
)
from legal_chatbot.retrieval.quality_repair.models import (
    SourceBinding,
    SourceId,
    _FrozenContract,
)

_MAX_UNITS = 4


class EvaluationProfile(StrEnum):
    LEGAL_ANSWER_QUALITY = "LEGAL_ANSWER_QUALITY_EVALUATION"


class EvaluationState(StrEnum):
    PLAN_ONLY = "PLAN_ONLY"


class EvaluationRoutingCode(StrEnum):
    EXPLICIT_ACTIVE = "EXPLICIT_ACTIVE"
    SOURCE_ACCESS_UNAVAILABLE = "SOURCE_ACCESS_UNAVAILABLE"
    UNBOUND_ACTIVE_SCOPE = "UNBOUND_ACTIVE_SCOPE"
    AMBIGUOUS_ACTIVE_SCOPE = "AMBIGUOUS_ACTIVE_SCOPE"


class EvaluationPlanUnit(_FrozenContract):
    """One private plan unit; it contains observations, never evidence or a query string."""

    unit_id: str = Field(min_length=1, max_length=32, exclude=True, repr=False)
    concept_query: ConceptQuery = Field(exclude=True, repr=False)
    observed_binding: SourceBinding = Field(exclude=True, repr=False)
    source_access_status: SourceAccessStatus
    routing_code: EvaluationRoutingCode
    read_source_ids: tuple[SourceId, ...] = Field(
        default=(), max_length=1, exclude=True, repr=False
    )
    active_source_scope: tuple[SourceId, ...] = Field(
        default=(), max_length=3, exclude=True, repr=False
    )

    @field_validator("read_source_ids", "active_source_scope")
    @classmethod
    def validate_source_ids(cls, value: tuple[SourceId, ...]) -> tuple[SourceId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("source identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_route(self) -> EvaluationPlanUnit:
        if self.observed_binding in (SourceBinding.VBQPPL, SourceBinding.VNU, SourceBinding.UEB):
            expected = SourceId(self.observed_binding.value)
            if self.routing_code is EvaluationRoutingCode.EXPLICIT_ACTIVE:
                if (
                    self.source_access_status is not SourceAccessStatus.ACTIVE
                    or self.read_source_ids != (expected,)
                    or self.active_source_scope
                ):
                    raise ValueError("active explicit routing requires its one active source")
            elif self.routing_code is EvaluationRoutingCode.SOURCE_ACCESS_UNAVAILABLE:
                if (
                    self.source_access_status is not SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE
                    or self.read_source_ids
                    or self.active_source_scope
                ):
                    raise ValueError("unavailable explicit routing cannot expose a source scope")
            else:
                raise ValueError("explicit bindings require an explicit routing code")
        elif self.observed_binding is SourceBinding.UNKNOWN:
            if (
                self.routing_code is not EvaluationRoutingCode.UNBOUND_ACTIVE_SCOPE
                or self.source_access_status is not SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE
                or self.read_source_ids
            ):
                raise ValueError("unknown bindings require an unbound, non-reading route")
        elif (
            self.routing_code is not EvaluationRoutingCode.AMBIGUOUS_ACTIVE_SCOPE
            or self.source_access_status is not SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE
            or self.read_source_ids
        ):
            raise ValueError("ambiguous bindings require an ambiguous, non-reading route")
        return self

    def to_public_dict(self) -> dict[str, object]:
        return {
            "source_access_status": self.source_access_status.value,
            "routing_code": self.routing_code.value,
            "query_terms_truncated": self.concept_query.truncated,
        }


class EvaluationExecutionPlan(_FrozenContract):
    """Immutable private plan with fixed zero-operation accounting."""

    profile: Literal[EvaluationProfile.LEGAL_ANSWER_QUALITY] = (
        EvaluationProfile.LEGAL_ANSWER_QUALITY
    )
    state: Literal[EvaluationState.PLAN_ONLY] = EvaluationState.PLAN_ONLY
    analysis: AnalyzerObservation = Field(exclude=True, repr=False)
    units: tuple[EvaluationPlanUnit, ...] = Field(
        min_length=1, max_length=_MAX_UNITS, exclude=True, repr=False
    )
    active_source_ids: tuple[SourceId, ...] = Field(
        min_length=1, max_length=3, exclude=True, repr=False
    )
    repair_allowed: Literal[False] = False
    provider_calls: Literal[0] = 0
    database_queries: Literal[0] = 0
    runtime_activation: Literal[False] = False

    @field_validator("active_source_ids")
    @classmethod
    def validate_active_source_ids(cls, value: tuple[SourceId, ...]) -> tuple[SourceId, ...]:
        if len(set(value)) != len(value):
            raise ValueError("active source identifiers must be unique")
        return value

    @model_validator(mode="after")
    def validate_units(self) -> EvaluationExecutionPlan:
        if tuple(unit.unit_id for unit in self.units) != tuple(
            unit.unit_id for unit in self.analysis.units
        ):
            raise ValueError("plan units must preserve analyzer unit order and identifiers")
        active = set(self.active_source_ids)
        for unit in self.units:
            if not set(unit.active_source_scope) <= active:
                raise ValueError("active source scope must be a subset of configured sources")
            if (
                unit.routing_code is EvaluationRoutingCode.EXPLICIT_ACTIVE
                and set(unit.read_source_ids) - active
            ):
                raise ValueError("active explicit routing must use a configured active source")
        return self

    def to_public_dict(self) -> dict[str, object]:
        access = {status.value: 0 for status in SourceAccessStatus}
        routes = {route.value: 0 for route in EvaluationRoutingCode}
        for unit in self.units:
            access[unit.source_access_status.value] += 1
            routes[unit.routing_code.value] += 1
        return {
            "profile": self.profile.value,
            "state": self.state.value,
            "unit_count": len(self.units),
            "intent": self.analysis.intent.value,
            "complexity": self.analysis.complexity.value,
            "ambiguity": self.analysis.ambiguity.value,
            "access_distribution": access,
            "routing_distribution": routes,
            "query_truncated_unit_count": sum(
                unit.concept_query.truncated for unit in self.units
            ),
            "unit_truncated": self.analysis.unit_truncated,
            "repair_allowed": self.repair_allowed,
            "provider_calls": self.provider_calls,
            "database_queries": self.database_queries,
            "runtime_activation": self.runtime_activation,
        }


@dataclass(frozen=True, slots=True)
class LegalAnswerQualityOrchestrator:
    """Compose analysis and policy into a plan without performing a source operation."""

    analyzer: LegalQuestionAnalyzer
    policy: AnalyzerPolicy

    def plan(self, question: str) -> EvaluationExecutionPlan:
        analysis = self.analyzer.analyze(question)
        self.policy.validate_known_observation(analysis)
        active_source_ids = tuple(
            sorted(self.policy.active_source_ids, key=lambda source: source.value)
        )
        units = tuple(self._plan_unit(unit, active_source_ids) for unit in analysis.units)
        return EvaluationExecutionPlan(
            analysis=analysis,
            units=units,
            active_source_ids=active_source_ids,
        )

    def _plan_unit(
        self,
        unit: AnalyzerUnit,
        active_source_ids: tuple[SourceId, ...],
    ) -> EvaluationPlanUnit:
        binding = unit.source_binding
        concept_query = unit.concept_query
        unit_id = unit.unit_id
        status = self.policy.access_status(binding)
        if binding in (SourceBinding.VBQPPL, SourceBinding.VNU, SourceBinding.UEB):
            source_id = SourceId(binding.value)
            if status is SourceAccessStatus.ACTIVE:
                return EvaluationPlanUnit(
                    unit_id=unit_id,
                    concept_query=concept_query,
                    observed_binding=binding,
                    source_access_status=status,
                    routing_code=EvaluationRoutingCode.EXPLICIT_ACTIVE,
                    read_source_ids=(source_id,),
                )
            return EvaluationPlanUnit(
                unit_id=unit_id,
                concept_query=concept_query,
                observed_binding=binding,
                source_access_status=status,
                routing_code=EvaluationRoutingCode.SOURCE_ACCESS_UNAVAILABLE,
            )
        if binding is SourceBinding.UNKNOWN:
            return EvaluationPlanUnit(
                unit_id=unit_id,
                concept_query=concept_query,
                observed_binding=binding,
                source_access_status=status,
                routing_code=EvaluationRoutingCode.UNBOUND_ACTIVE_SCOPE,
                active_source_scope=active_source_ids,
            )
        return EvaluationPlanUnit(
            unit_id=unit_id,
            concept_query=concept_query,
            observed_binding=binding,
            source_access_status=status,
            routing_code=EvaluationRoutingCode.AMBIGUOUS_ACTIVE_SCOPE,
            active_source_scope=active_source_ids,
        )
