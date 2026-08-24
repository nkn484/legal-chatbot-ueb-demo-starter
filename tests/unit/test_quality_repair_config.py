import json

import pytest
from pydantic import ValidationError

from legal_chatbot.retrieval.config import RetrievalSettings
from legal_chatbot.retrieval.quality_repair.analyzer import (
    AnalyzerObservation,
    AnalyzerPolicy,
    AnalyzerUnit,
    GenericIntent,
    QueryComplexity,
    SourceScope,
    derived_source_scope,
)
from legal_chatbot.retrieval.quality_repair.models import SourceId
from legal_chatbot.retrieval.quality_repair.trace import QualityRepairMetrics, QualityRepairTrace


def test_quality_repair_defaults_are_inert() -> None:
    settings = RetrievalSettings()
    assert settings.quality_repair_enabled is False
    assert settings.quality_strategy == "disabled"


def test_quality_repair_requires_an_exact_named_profile_flag_set() -> None:
    with pytest.raises(ValidationError):
        RetrievalSettings(quality_title_search_enabled=True)
    with pytest.raises(ValidationError):
        RetrievalSettings(quality_repair_enabled=True, quality_strategy="disabled")
    with pytest.raises(ValidationError):
        RetrievalSettings(
            quality_repair_enabled=True,
            quality_strategy="quality_retrieval_hybrid_v1",
            quality_title_search_enabled=True,
            quality_selected_pool=8,
        )
    settings = RetrievalSettings(
        quality_repair_enabled=True,
        quality_strategy="quality_retrieval_hybrid_v1",
        quality_title_search_enabled=True,
        quality_hybrid_fusion_enabled=True,
        quality_selected_pool=8,
    )
    assert settings.quality_strategy == "quality_retrieval_hybrid_v1"
    full = RetrievalSettings(
        quality_repair_enabled=True,
        quality_strategy="quality_retrieval_full_candidate_v1",
        quality_title_search_enabled=True,
        quality_hybrid_fusion_enabled=True,
        quality_query_planner_enabled=True,
        quality_dynamic_evidence_enabled=True,
        quality_repair_retrieval_enabled=True,
        quality_selected_pool=8,
    )
    assert full.quality_strategy == "quality_retrieval_full_candidate_v1"


def test_safe_trace_excludes_analyzer_and_repair_query_text() -> None:
    trace = QualityRepairTrace(
        strategy_name="quality_retrieval_hybrid_v1",
        strategy_version="quality-retrieval-a1-v1",
        analyzer=AnalyzerObservation(
            intent=GenericIntent.GENERAL,
            intent_label="private intent label",
            entities=("private entity",),
            sub_intents=("private sub-intent",),
            complexity=QueryComplexity.SIMPLE,
            source_scope=SourceScope.NONE,
            units=(AnalyzerUnit(unit_id="private-unit", source_scope=SourceScope.NONE),),
            decomposition_text="private decomposition",
        ),
        repair_query_text="private repair query",
        metrics=QualityRepairMetrics(
            input_candidate_count=0,
            collapsed_candidate_count=0,
            eligible_candidate_count=0,
            final_evidence_count=0,
        ),
    )
    public = str(trace.to_public_dict())
    serialized = json.dumps(trace.model_dump(mode="json"))
    representation = repr(trace)
    for sentinel in (
        "private intent label",
        "private entity",
        "private sub-intent",
        "private-unit",
        "private decomposition",
        "private repair query",
    ):
        assert sentinel not in serialized
        assert sentinel not in representation
        assert sentinel not in public


def test_analyzer_policy_accepts_server_owned_source_scopes_without_hardcoding_them() -> None:
    observation = AnalyzerObservation(
        intent=GenericIntent.GENERAL,
        complexity=QueryComplexity.SIMPLE,
        source_scope=SourceScope.EXPLICIT_SOURCE,
        units=(
            AnalyzerUnit(
                unit_id="opaque-unit",
                source_scope=SourceScope.EXPLICIT_SOURCE,
                source_ids=(SourceId.VNU,),
            ),
        ),
    )
    with pytest.raises(ValueError, match="analyzer policy"):
        AnalyzerPolicy(active_source_ids=(SourceId.VBQPPL,)).validate_observation(observation)
    assert AnalyzerPolicy(
        active_source_ids=(SourceId.VBQPPL, SourceId.VNU, SourceId.UEB)
    ).validate_observation(observation) is observation


def test_analyzer_source_scope_is_strictly_derived_from_units() -> None:
    vbqppl = AnalyzerUnit(
        unit_id="unit-vbqppl",
        source_scope=SourceScope.EXPLICIT_SOURCE,
        source_ids=(SourceId.VBQPPL,),
    )
    ueb = AnalyzerUnit(
        unit_id="unit-ueb",
        source_scope=SourceScope.EXPLICIT_SOURCE,
        source_ids=(SourceId.UEB,),
    )
    none = AnalyzerUnit(unit_id="unit-none", source_scope=SourceScope.NONE)
    ambiguous = AnalyzerUnit(unit_id="unit-ambiguous", source_scope=SourceScope.AMBIGUOUS_SOURCE)
    explicit = AnalyzerObservation(
        intent=GenericIntent.GENERAL,
        complexity=QueryComplexity.MULTI_SOURCE,
        source_scope=SourceScope.EXPLICIT_SOURCE,
        units=(vbqppl, ueb, none),
    )
    assert derived_source_scope(explicit.units) is SourceScope.EXPLICIT_SOURCE
    assert AnalyzerPolicy(
        active_source_ids=(SourceId.VBQPPL, SourceId.VNU, SourceId.UEB)
    ).validate_observation(explicit) is explicit
    with pytest.raises(ValueError, match="analyzer policy"):
        AnalyzerPolicy(active_source_ids=(SourceId.VBQPPL,)).validate_observation(explicit)
    mixed_ambiguous = AnalyzerObservation(
        intent=GenericIntent.GENERAL,
        complexity=QueryComplexity.AMBIGUOUS,
        source_scope=SourceScope.AMBIGUOUS_SOURCE,
        units=(ambiguous, vbqppl, none),
    )
    assert derived_source_scope(mixed_ambiguous.units) is SourceScope.AMBIGUOUS_SOURCE
    with pytest.raises(ValidationError, match="derived per-unit"):
        AnalyzerObservation(
            intent=GenericIntent.GENERAL,
            complexity=QueryComplexity.AMBIGUOUS,
            source_scope=SourceScope.EXPLICIT_SOURCE,
            units=(ambiguous, vbqppl),
        )


def test_analyzer_unit_private_source_and_query_fields_do_not_serialize() -> None:
    unit = AnalyzerUnit(
        unit_id="private-unit-id",
        source_scope=SourceScope.EXPLICIT_SOURCE,
        source_ids=(SourceId.VBQPPL,),
        query_text="private unit query",
    )
    serialized = json.dumps(unit.model_dump(mode="json"))
    assert "private-unit-id" not in serialized
    assert SourceId.VBQPPL.value not in serialized
    assert "private unit query" not in serialized
    assert "private-unit-id" not in repr(unit)
