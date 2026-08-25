"""Bounded Vietnamese material legal-dimension decomposition for P2 fallback."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from legal_chatbot.legal_evidence.models import PreferredSourceTier, SubIntent


@dataclass(frozen=True)
class _Dimension:
    code: str
    description: str
    concepts: tuple[str, ...]
    reason_codes: tuple[str, ...]
    object_scope: str | None = None


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _safe_concepts(values: tuple[str, ...], fallback: str) -> tuple[str, ...]:
    """Normalize before model construction so generic fallback never emits invalid concepts."""

    unique: list[str] = []
    for value in (*values, fallback):
        normalized = _normalized(value)
        if normalized and len(normalized) <= 128 and normalized not in unique:
            unique.append(normalized)
        if len(unique) == 8:
            break
    return tuple(unique)


class DeterministicMaterialDecomposer:
    """Extract independently retrievable legal dimensions without benchmark identifiers."""

    def decompose(
        self,
        question: str,
        *,
        actor_scope: str | None,
        preferred_source_tiers: tuple[PreferredSourceTier, ...],
    ) -> tuple[SubIntent, ...]:
        text = _normalized(question)
        dimensions = self._dimensions(text)
        if not dimensions:
            dimensions = (
                _Dimension(
                    code="GENERAL_LEGAL_ISSUE",
                    description="general legal issue",
                    concepts=_safe_concepts(
                        tuple(word for word in text.split() if len(word) > 2),
                        "general legal issue",
                    ),
                    reason_codes=("SAFE_SINGLE_ISSUE_FALLBACK",),
                ),
            )
        return tuple(
            SubIntent(
                code=item.code,
                description=item.description,
                actor_scope=actor_scope,
                object_scope=item.object_scope,
                retrieval_concepts=_safe_concepts(item.concepts, item.description),
                preferred_source_tiers=preferred_source_tiers,
                decomposition_reason_codes=item.reason_codes,
            )
            for item in dimensions[:4]
        )

    def materially_multidimensional(self, question: str) -> bool:
        return len(self._dimensions(_normalized(question))) > 1

    @staticmethod
    def _dimensions(text: str) -> tuple[_Dimension, ...]:
        authority = _contains_any(text, ("thẩm quyền", "ai có quyền", "cơ quan nào"))
        procedure = _contains_any(text, ("quy trình", "thủ tục", "các bước", "trình tự"))
        grounds = _contains_any(text, ("căn cứ", "điều kiện", "tiêu chí"))
        purchase = _contains_any(text, ("mua sắm", "mua tài sản", "mua mới"))
        management = _contains_any(text, ("quản lý", "quản trị", "theo dõi"))
        inventory = _contains_any(text, ("kiểm kê", "kiểm tra tài sản"))
        warning = _contains_any(text, ("cảnh báo học tập", "cảnh báo"))
        dismissal = _contains_any(text, ("buộc thôi học", "thôi học"))
        finance = _contains_any(text, ("tài chính", "kinh phí", "nguồn kinh phí"))
        research_management = _contains_any(text, ("nhiệm vụ nghiên cứu", "phát triển công nghệ"))
        dimensions: list[_Dimension] = []

        if purchase and authority:
            dimensions.append(
                _Dimension(
                    "PURCHASE_AUTHORITY",
                    "purchase authority",
                    ("mua sắm", "tài sản", "thẩm quyền"),
                    ("PURCHASE_OBJECT", "AUTHORITY_DIMENSION"),
                    "asset purchase",
                )
            )
        elif authority:
            dimensions.append(
                _Dimension(
                    "AUTHORITY",
                    "authority",
                    ("thẩm quyền",),
                    ("AUTHORITY_DIMENSION",),
                )
            )

        if purchase and procedure:
            dimensions.append(
                _Dimension(
                    "PURCHASE_PROCEDURE",
                    "purchase procedure",
                    ("mua sắm", "tài sản", "quy trình"),
                    ("PURCHASE_OBJECT", "PROCEDURE_DIMENSION"),
                    "asset purchase",
                )
            )

        if warning and grounds:
            dimensions.append(
                _Dimension(
                    "WARNING_GROUNDS",
                    "academic warning grounds",
                    ("cảnh báo học tập", "căn cứ"),
                    ("WARNING_ACTION", "GROUNDS_DIMENSION"),
                    "academic warning",
                )
            )
        if dismissal and grounds:
            dimensions.append(
                _Dimension(
                    "DISMISSAL_GROUNDS",
                    "academic dismissal grounds",
                    ("buộc thôi học", "căn cứ"),
                    ("DISMISSAL_ACTION", "GROUNDS_DIMENSION"),
                    "academic dismissal",
                )
            )
        if (warning or dismissal) and procedure:
            dimensions.append(
                _Dimension(
                    "WARNING_DISMISSAL_PROCESS",
                    "warning and dismissal process",
                    ("cảnh báo học tập", "buộc thôi học", "quy trình"),
                    ("ACADEMIC_STATUS_ACTION", "PROCEDURE_DIMENSION"),
                    "academic status process",
                )
            )

        if management:
            dimensions.append(
                _Dimension(
                    "POST_PURCHASE_MANAGEMENT" if purchase else "MANAGEMENT",
                    "post-purchase asset management" if purchase else "management",
                    ("quản lý", "tài sản") if purchase else ("quản lý",),
                    (("PURCHASE_OBJECT",) if purchase else ()) + ("MANAGEMENT_DIMENSION",),
                    "asset management" if purchase else None,
                )
            )
        if inventory:
            dimensions.append(
                _Dimension(
                    "INVENTORY",
                    "asset inventory",
                    ("kiểm kê", "tài sản"),
                    ("INVENTORY_DIMENSION",),
                    "asset inventory",
                )
            )
        if finance:
            dimensions.append(
                _Dimension(
                    "FINANCIAL_REQUIREMENTS",
                    "financial requirements",
                    ("tài chính", "kinh phí"),
                    ("FINANCIAL_DIMENSION",),
                    "financial requirements",
                )
            )
        if research_management:
            dimensions.append(
                _Dimension(
                    "RESEARCH_MANAGEMENT",
                    "research management",
                    ("nghiên cứu", "phát triển công nghệ", "quản lý"),
                    ("RESEARCH_OBJECT", "MANAGEMENT_DIMENSION"),
                    "research task",
                )
            )
        if procedure and not purchase and not (warning or dismissal):
            dimensions.append(
                _Dimension(
                    "PROCEDURE",
                    "procedure",
                    ("quy trình", "thủ tục"),
                    ("PROCEDURE_DIMENSION",),
                )
            )
        if grounds and not (warning or dismissal):
            dimensions.append(
                _Dimension(
                    "GROUNDS_OR_CONDITIONS",
                    "grounds or conditions",
                    ("căn cứ", "điều kiện"),
                    ("GROUNDS_DIMENSION",),
                )
            )
        return tuple(dict.fromkeys(dimensions))


__all__ = ["DeterministicMaterialDecomposer"]
