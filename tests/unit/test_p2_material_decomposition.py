import asyncio
from pathlib import Path

import pytest

from legal_chatbot.legal_evidence import AnalyzerOutcome, create_legal_case
from legal_chatbot.legal_evidence.analyzer import (
    LegalQuestionAnalyzerSettings,
    LLMLegalQuestionAnalyzer,
)


def _codes(question: str) -> tuple[str | None, ...]:
    analyzer = LLMLegalQuestionAnalyzer(None, settings=LegalQuestionAnalyzerSettings(enabled=False))
    result = asyncio.run(analyzer.analyze(create_legal_case(question)))
    return tuple(item.code for item in result.sub_intents)


def test_single_issue_remains_one_material_sub_intent() -> None:
    assert _codes("Điều kiện đăng ký học phần là gì?") == ("GROUNDS_OR_CONDITIONS",)


def test_authority_and_procedure_are_distinct_material_dimensions() -> None:
    assert _codes("Cơ quan nào có thẩm quyền và quy trình xử lý là gì?") == (
        "AUTHORITY",
        "PROCEDURE",
    )


def test_purchase_management_inventory_preserve_bounded_distinct_dimensions() -> None:
    assert _codes(
        "Nhà trường mua sắm tài sản, quản lý và kiểm kê theo thẩm quyền và quy trình nào?"
    ) == (
        "PURCHASE_AUTHORITY",
        "PURCHASE_PROCEDURE",
        "POST_PURCHASE_MANAGEMENT",
        "INVENTORY",
    )


def test_warning_dismissal_and_process_remain_distinct() -> None:
    assert _codes("Sinh viên bị cảnh báo hoặc buộc thôi học theo căn cứ và quy trình nào?") == (
        "WARNING_GROUNDS",
        "DISMISSAL_GROUNDS",
        "WARNING_DISMISSAL_PROCESS",
    )


def test_duplicate_dimension_wording_is_deduplicated() -> None:
    assert _codes("Thẩm quyền, thẩm quyền và quy trình xử lý là gì?") == (
        "AUTHORITY",
        "PROCEDURE",
    )


def test_more_than_four_dimensions_uses_bounded_materiality_selection() -> None:
    codes = _codes(
        "Thẩm quyền, điều kiện, quy trình, quản lý, kiểm kê và tài chính được quy định thế nào?"
    )
    assert 1 <= len(codes) <= 4
    assert len(codes) == len(set(codes))


def test_malformed_but_bounded_question_uses_safe_single_issue_fallback() -> None:
    analyzer = LLMLegalQuestionAnalyzer(None, settings=LegalQuestionAnalyzerSettings(enabled=False))
    result = asyncio.run(analyzer.analyze(create_legal_case("Nội dung này áp dụng thế nào?")))

    assert result.outcome is AnalyzerOutcome.FALLBACK_DISABLED
    assert len(result.sub_intents) == 1
    assert result.sub_intents[0].code == "GENERAL_LEGAL_ISSUE"


def test_generic_fallback_concepts_are_deduplicated_and_schema_valid() -> None:
    codes = _codes("Học viên cao học phải tuân thủ quy định nào trong quá trình học?")

    assert codes == ("GENERAL_LEGAL_ISSUE",)


@pytest.mark.asyncio
async def test_structured_provider_single_label_is_rejected_for_multidimensional_question() -> None:
    class _Provider:
        async def generate(self, request):
            from legal_chatbot.providers.models import GenerationResult

            return GenerationResult(
                text=(
                    '{"main_intent":"authority","legal_actor":null,'
                    '"legal_action_event":null,"explicit_time":[],"legal_topics":[],'
                    '"ambiguity":false,"sub_intents":[{"description":"authority",'
                    '"retrieval_concepts":["thẩm quyền"],"preferred_source_tiers":[]}],'
                    '"preferred_source_tiers":[],"retrieval_concepts":["thẩm quyền"]}'
                ),
                provider="stub",
                model="stub",
                duration_ms=1,
            )

    analyzer = LLMLegalQuestionAnalyzer(
        _Provider(), settings=LegalQuestionAnalyzerSettings(enabled=True, deterministic_first=False)
    )
    result = await analyzer.analyze(
        create_legal_case("Thẩm quyền và quy trình giải quyết yêu cầu là gì?")
    )

    assert result.outcome is AnalyzerOutcome.FALLBACK_INSUFFICIENT_DECOMPOSITION
    assert tuple(item.code for item in result.sub_intents) == ("AUTHORITY", "PROCEDURE")


def test_p2_runtime_has_no_oracle_or_benchmark_case_markers() -> None:
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/legal_chatbot/legal_evidence/analyzer").glob("*.py")
    ).casefold()

    assert "oracle" not in content
    assert not any(f"q{number:02d}" in content for number in range(1, 11))
