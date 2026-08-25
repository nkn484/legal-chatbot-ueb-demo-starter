"""P2 LLM legal-question analysis boundary."""

from .models import (
    LEGAL_QUESTION_ANALYZER_VERSION,
    LegalQuestionAnalysisProposal,
    LegalQuestionAnalyzerSettings,
    LegalSubIntentProposal,
)
from .parser import StrictLegalQuestionAnalysisParser
from .prompt import (
    LEGAL_QUESTION_ANALYZER_PROMPT_VERSION,
    LEGAL_QUESTION_ANALYZER_SCHEMA_VERSION,
    build_legal_question_analyzer_prompt,
    legal_question_analysis_output_format,
)
from .service import LLMLegalQuestionAnalyzer

__all__ = [
    "LEGAL_QUESTION_ANALYZER_PROMPT_VERSION",
    "LEGAL_QUESTION_ANALYZER_SCHEMA_VERSION",
    "LEGAL_QUESTION_ANALYZER_VERSION",
    "LegalQuestionAnalysisProposal",
    "LegalQuestionAnalyzerSettings",
    "LegalSubIntentProposal",
    "LLMLegalQuestionAnalyzer",
    "StrictLegalQuestionAnalysisParser",
    "build_legal_question_analyzer_prompt",
    "legal_question_analysis_output_format",
]
