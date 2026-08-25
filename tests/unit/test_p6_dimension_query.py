from legal_chatbot.legal_evidence import SubIntent
from legal_chatbot.legal_evidence.pinpoint.query import build_pinpoint_query


def test_dimension_aware_query_preserves_ground_terms_without_case_specific_input() -> None:
    sub_intent = SubIntent(
        code="WARNING_GROUNDS",
        description="academic warning grounds",
        retrieval_concepts=("cảnh báo học tập", "căn cứ"),
    )

    query = build_pinpoint_query(sub_intent)

    assert '"cảnh báo học tập"' in query
    assert '"kết quả học tập"' in query
    assert " OR " in query


def test_unknown_dimension_falls_back_to_its_bounded_retrieval_concepts() -> None:
    sub_intent = SubIntent(
        code="GENERAL_LEGAL_ISSUE",
        description="general legal issue",
        retrieval_concepts=("quyền", "nghĩa vụ"),
    )

    assert build_pinpoint_query(sub_intent) == '"quyền" OR "nghĩa vụ"'
