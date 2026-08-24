import json
import re
from pathlib import Path

import pytest

from legal_chatbot.retrieval.quality_repair.analyzer import (
    AmbiguityCode,
    AnalyzerPolicy,
    GenericIntent,
    LegalQuestionAnalyzer,
    QueryComplexity,
    SourceAccessStatus,
)
from legal_chatbot.retrieval.quality_repair.models import SourceBinding, SourceId


def test_simple_paraphrased_question_remains_one_deterministic_unit() -> None:
    analyzer = LegalQuestionAnalyzer()
    first = analyzer.analyze("Người lao động cần điều kiện gì để đăng ký bảo hiểm?")
    second = analyzer.analyze("Người lao động cần điều kiện gì để đăng ký bảo hiểm?")

    assert first == second
    assert first.complexity is QueryComplexity.SIMPLE
    assert len(first.units) == 1
    assert first.units[0].unit_id == "u01"
    assert first.legal_actor == "NGUOI_LAO_DONG"
    assert first.action_event == "DANG_KY"


def test_material_stages_are_bounded_and_do_not_split_a_simple_conjunction() -> None:
    analyzer = LegalQuestionAnalyzer()
    simple = analyzer.analyze("Thủ tục và điều kiện đăng ký bảo hiểm là gì?")
    multi = analyzer.analyze(
        "Thủ tục đăng ký bảo hiểm là gì; sau đó nộp hồ sơ ở đâu; rồi khiếu nại thế nào?"
    )

    assert len(simple.units) == 1
    assert multi.complexity is QueryComplexity.MULTI_INTENT
    assert [unit.unit_id for unit in multi.units] == ["u01", "u02", "u03"]


def test_source_binding_is_observation_only_and_ambiguous_cues_are_not_forced() -> None:
    analyzer = LegalQuestionAnalyzer()
    explicit = analyzer.analyze("Theo VBQPPL, thủ tục đăng ký là gì?")
    ambiguous = analyzer.analyze("Theo VBQPPL và VNU, thủ tục đăng ký là gì?")

    assert explicit.units[0].source_binding is SourceBinding.VBQPPL
    assert ambiguous.units[0].source_binding is SourceBinding.AMBIGUOUS
    assert ambiguous.units[0].source_ids == ()
    assert ambiguous.ambiguity is AmbiguityCode.SOURCE_AMBIGUOUS
    assert ambiguous.complexity is QueryComplexity.AMBIGUOUS


def test_private_time_document_and_concept_terms_do_not_leak_from_models_or_trace_view() -> None:
    document_number = "/".join(("12", "2026", "TT-ABC"))
    observation = LegalQuestionAnalyzer().analyze(
        f"Tại Công ty Ánh Dương, năm 2026 áp dụng văn bản số {document_number} thế nào?"
    )
    unit = observation.units[0]
    sentinels = ("Công ty Ánh Dương", "2026", document_number)
    serialized = json.dumps(observation.model_dump(mode="json"), ensure_ascii=False)
    public = json.dumps(observation.to_public_dict(), ensure_ascii=False)
    representation = repr(observation)

    assert unit.explicit_time
    assert unit.concept_query.document_number_tokens == (document_number,)
    for sentinel in sentinels:
        assert sentinel not in serialized
        assert sentinel not in public
        assert sentinel not in representation
    assert "query_unit_count" in observation.to_public_dict()
    assert "binding_distribution" in observation.to_public_dict()


def test_unit_and_term_caps_and_invalid_text_fail_closed() -> None:
    analyzer = LegalQuestionAnalyzer()
    observation = analyzer.analyze(
        "Thủ tục đăng ký; thủ tục nộp; thủ tục cấp; thủ tục gia hạn; thủ tục khiếu nại?"
    )

    assert len(observation.units) == 4
    assert observation.unit_truncated is True
    with pytest.raises(ValueError):
        analyzer.analyze("\x00không hợp lệ")
    with pytest.raises(ValueError):
        analyzer.analyze("x" * 2_001)


def test_analyzer_module_has_no_external_boundary_imports_or_case_markers() -> None:
    content = Path("src/legal_chatbot/retrieval/quality_repair/analyzer.py").read_text(
        encoding="utf-8"
    ).lower()
    forbidden = ("sqlalchemy", "legal_chatbot.chat", "chat.planner", "provider", "llm")

    assert not any(term in content for term in forbidden)
    assert "benchmark" not in content
    assert not re.search(r"\bq(?:0[1-9]|10)\b", content)
    assert "question ==" not in content
    assert "question !=" not in content
    assert not re.search(r"\b\d{1,5}/\d{2,4}/[a-z]", content)


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("Điều kiện để đăng ký là gì?", GenericIntent.ELIGIBILITY),
        ("Thủ tục nộp hồ sơ ra sao?", GenericIntent.PROCEDURE),
        ("Cơ quan nào có thẩm quyền phê duyệt?", GenericIntent.AUTHORITY),
        ("Hành vi nào bị nghiêm cấm?", GenericIntent.PROHIBITION),
        ("Nghĩa vụ báo cáo được quy định thế nào?", GenericIntent.OBLIGATION),
        ("Quyền khiếu nại gồm những gì?", GenericIntent.RIGHTS),
        ("Hậu quả khi chấm dứt là gì?", GenericIntent.LEGAL_CONSEQUENCE),
        ("Tiêu chí đánh giá là gì?", GenericIntent.EVALUATION_CRITERIA),
        ("Việc lưu trữ văn bản được thực hiện ra sao?", GenericIntent.DOCUMENT_MANAGEMENT),
        ("Văn bản còn hiệu lực áp dụng không?", GenericIntent.VALIDITY_APPLICABILITY),
        ("Tìm văn bản quy định về hồ sơ.", GenericIntent.DOCUMENT_LOOKUP),
        ("Xin giải thích nội dung.", GenericIntent.GENERAL),
    ],
)
def test_intent_taxonomy_uses_stable_codes(question: str, intent: GenericIntent) -> None:
    assert LegalQuestionAnalyzer().analyze(question).intent is intent


def test_coordinated_actions_and_paraphrases_are_generalized_and_deterministic() -> None:
    analyzer = LegalQuestionAnalyzer()
    first = analyzer.analyze("Đăng ký và nộp hồ sơ; sau đó cơ quan thẩm định.")
    second = analyzer.analyze("Đăng ký và nộp hồ sơ; sau đó cơ quan thẩm định.")

    assert first == second
    assert first.intent is GenericIntent.MULTI_STAGE_PROCESS
    assert len(first.units) == 3
    assert first.complexity is QueryComplexity.MULTI_INTENT


def test_one_slash_document_number_is_private_and_organization_is_not_greedy() -> None:
    document_number = "/".join(("18", "QD-UBND"))
    observation = LegalQuestionAnalyzer().analyze(
        f"Công ty Ánh Dương áp dụng số {document_number} như thế nào trong thủ tục đăng ký?"
    )
    unit = observation.units[0]

    assert unit.concept_query.document_number_tokens == (document_number,)
    assert unit.organization_scope == ("Công ty Ánh Dương",)
    assert document_number not in json.dumps(observation.model_dump(mode="json"))


def test_planned_source_cues_are_known_without_claiming_active_access() -> None:
    policy = AnalyzerPolicy(active_source_ids=(SourceId.VBQPPL,))
    vnu = LegalQuestionAnalyzer().analyze("Theo ĐHQGHN, thủ tục đăng ký là gì?")
    ueb = LegalQuestionAnalyzer().analyze("Theo UEB, thủ tục đăng ký là gì?")
    generic_school = LegalQuestionAnalyzer().analyze("Tại trường đại học kinh tế, thủ tục là gì?")

    assert policy.validate_known_observation(vnu) is vnu
    assert policy.validate_known_observation(ueb) is ueb
    assert policy.access_status(SourceBinding.VBQPPL) is SourceAccessStatus.ACTIVE
    assert policy.access_status(SourceBinding.VNU) is SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE
    assert policy.access_status(SourceBinding.UEB) is SourceAccessStatus.SOURCE_ACCESS_UNAVAILABLE
    assert generic_school.units[0].source_binding is SourceBinding.UNKNOWN
