"""Dimension-aware, bounded P6 query construction without benchmark case rules."""

from __future__ import annotations

from legal_chatbot.legal_evidence.models import SubIntent

_DIMENSION_TERMS = {
    "WARNING_GROUNDS": ("cảnh báo học tập", "điều kiện", "căn cứ", "kết quả học tập"),
    "DISMISSAL_GROUNDS": ("buộc thôi học", "điều kiện", "căn cứ", "kết quả học tập"),
    "WARNING_DISMISSAL_PROCESS": (
        "cảnh báo học tập",
        "buộc thôi học",
        "quy trình",
        "quyết định",
        "thông báo",
    ),
    "PURCHASE_AUTHORITY": ("mua sắm", "tài sản", "thẩm quyền"),
    "PURCHASE_PROCEDURE": ("mua sắm", "tài sản", "quy trình"),
    "POST_PURCHASE_MANAGEMENT": ("quản lý", "tài sản", "sử dụng"),
    "INVENTORY": ("kiểm kê", "tài sản", "quản lý"),
    "FINANCIAL_REQUIREMENTS": ("tài chính", "kinh phí", "quản lý"),
    "RESEARCH_MANAGEMENT": ("nghiên cứu", "công nghệ", "quản lý"),
}


def build_pinpoint_query(sub_intent: SubIntent) -> str:
    """Use OR-connected legal-dimension terms so FTS is not an accidental all-term gate."""

    values = tuple(
        dict.fromkeys(
            (*_DIMENSION_TERMS.get(sub_intent.code or "", ()), *sub_intent.retrieval_concepts)
        )
    )
    bounded = tuple(value.strip() for value in values if value.strip())[:8]
    if not bounded:
        return sub_intent.description
    return " OR ".join(f'"{value}"' for value in bounded)


__all__ = ["build_pinpoint_query"]
