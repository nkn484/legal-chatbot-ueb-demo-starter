"""Provider- and adapter-neutral ports for later legal-evidence stages."""

from typing import Protocol

from .models import LegalCaseContext, LegalQuestionAnalysisResult


class LegalQuestionAnalyzerPort(Protocol):
    """Produce private request analysis without exposing provider implementation."""

    async def analyze(self, context: LegalCaseContext) -> LegalQuestionAnalysisResult:
        """Return bounded analysis for the supplied request-local context."""
        ...


class LegalEvidenceInvestigationPort(Protocol):
    """Advance one request through a future configured investigation profile."""

    async def investigate(self, context: LegalCaseContext) -> LegalCaseContext:
        """Return a new immutable context without mutating the input."""
        ...


__all__ = ["LegalEvidenceInvestigationPort", "LegalQuestionAnalyzerPort"]
