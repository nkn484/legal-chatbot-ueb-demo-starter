import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from legal_chatbot.diagnostics.evaluation.orchestrator import (
    EvaluationExecutionPlan,
    EvaluationPlanUnit,
    EvaluationRoutingCode,
    LegalAnswerQualityOrchestrator,
)
from legal_chatbot.retrieval.quality_repair.analyzer import (
    AnalyzerPolicy,
    ConceptQuery,
    LegalQuestionAnalyzer,
    SourceAccessStatus,
)
from legal_chatbot.retrieval.quality_repair.models import SourceBinding, SourceId


def _orchestrator(*active: SourceId) -> LegalAnswerQualityOrchestrator:
    return LegalAnswerQualityOrchestrator(
        analyzer=LegalQuestionAnalyzer(), policy=AnalyzerPolicy(active_source_ids=active)
    )


def test_explicit_active_and_inactive_bindings_have_distinct_non_reading_plans() -> None:
    orchestrator = _orchestrator(SourceId.VBQPPL)
    active = orchestrator.plan("Theo VBQPPL, thủ tục đăng ký là gì?")
    inactive = orchestrator.plan("Theo VNU, thủ tục đăng ký là gì?")

    assert active.units[0].routing_code is EvaluationRoutingCode.EXPLICIT_ACTIVE
    assert active.units[0].read_source_ids == (SourceId.VBQPPL,)
    assert inactive.units[0].routing_code is EvaluationRoutingCode.SOURCE_ACCESS_UNAVAILABLE
    assert inactive.units[0].source_access_status is SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE
    assert inactive.units[0].read_source_ids == ()


def test_unknown_and_ambiguous_bindings_never_resolve_a_read_source() -> None:
    orchestrator = _orchestrator(SourceId.VBQPPL)
    unknown = orchestrator.plan("Thủ tục đăng ký bảo hiểm là gì?")
    ambiguous = orchestrator.plan("Theo VBQPPL và VNU, thủ tục đăng ký là gì?")

    assert unknown.units[0].observed_binding is SourceBinding.UNKNOWN
    assert unknown.units[0].routing_code is EvaluationRoutingCode.UNBOUND_ACTIVE_SCOPE
    assert ambiguous.units[0].observed_binding is SourceBinding.AMBIGUOUS
    assert ambiguous.units[0].routing_code is EvaluationRoutingCode.AMBIGUOUS_ACTIVE_SCOPE
    assert all(not unit.read_source_ids for unit in (*unknown.units, *ambiguous.units))


def test_multi_unit_plan_is_deterministic_and_records_zero_operations() -> None:
    orchestrator = _orchestrator(SourceId.VBQPPL)
    question = "Theo VBQPPL, đăng ký; sau đó nộp hồ sơ theo UEB."
    first = orchestrator.plan(question)
    second = orchestrator.plan(question)

    assert first == second
    assert len(first.units) == 2
    assert [unit.routing_code for unit in first.units] == [
        EvaluationRoutingCode.EXPLICIT_ACTIVE,
        EvaluationRoutingCode.SOURCE_ACCESS_UNAVAILABLE,
    ]
    assert first.repair_allowed is False
    assert first.provider_calls == 0
    assert first.database_queries == 0
    assert first.runtime_activation is False


def test_private_plan_data_does_not_leak_from_model_or_public_serialization() -> None:
    document_number = "/".join(("18", "QD-UBND"))
    plan = _orchestrator(SourceId.VBQPPL).plan(
        f"Tại Công ty Ánh Dương, theo VBQPPL số {document_number}, thủ tục đăng ký là gì?"
    )
    sentinels = ("Công ty Ánh Dương", document_number, "u01", "VBQPPL")
    serialized = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)
    public = json.dumps(plan.to_public_dict(), ensure_ascii=False)

    for sentinel in sentinels:
        assert sentinel not in serialized
        assert sentinel not in public
        assert sentinel not in repr(plan)


def test_plan_contract_rejects_inconsistent_routes_and_is_immutable() -> None:
    with pytest.raises(ValidationError):
        EvaluationPlanUnit(
            unit_id="u01",
            concept_query=ConceptQuery(),
            observed_binding=SourceBinding.VNU,
            source_access_status=SourceAccessStatus.ACTIVE,
            routing_code=EvaluationRoutingCode.EXPLICIT_ACTIVE,
            read_source_ids=(SourceId.VNU,),
            active_source_scope=(SourceId.VBQPPL,),
        )

    plan = _orchestrator(SourceId.VBQPPL).plan("Thủ tục đăng ký là gì?")
    with pytest.raises(ValidationError):
        plan.provider_calls = 1  # type: ignore[misc]
    with pytest.raises(ValidationError):
        EvaluationExecutionPlan(
            analysis=plan.analysis,
            units=plan.units,
            active_source_ids=(SourceId.VBQPPL, SourceId.VBQPPL),
        )


def test_orchestrator_module_has_no_execution_boundary_imports_or_case_markers() -> None:
    content = Path(
        "src/legal_chatbot/diagnostics/evaluation/orchestrator.py"
    ).read_text(encoding="utf-8").lower()
    forbidden_imports = (
        "import sqlalchemy",
        "from sqlalchemy",
        "retrievalservice",
        "legal_chatbot.runtime",
        "legal_chatbot.chat",
        "chat.planner",
        "legal_chatbot.adapters",
    )

    assert not any(term in content for term in forbidden_imports)
    assert "query_text" not in content
    assert "benchmark" not in content
    assert not re.search(r"\bq(?:0[1-9]|10)\b", content)
    assert "question ==" not in content
