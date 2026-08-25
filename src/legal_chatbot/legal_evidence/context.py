"""Construction helpers for private, immutable legal-case request state."""

from __future__ import annotations

from .models import LegalCaseContext


def create_legal_case(
    question_text: str,
    *,
    organization_context: str | None = None,
    conversation_summary: str | None = None,
) -> LegalCaseContext:
    """Create the initial request state without serializing user-derived text."""

    return LegalCaseContext(
        question_text=question_text,
        organization_context=organization_context,
        conversation_summary=conversation_summary,
    )


__all__ = ["create_legal_case"]
