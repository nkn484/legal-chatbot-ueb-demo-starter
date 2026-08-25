"""Provider-neutral P2 analyzer with deterministic fail-closed fallback."""

from __future__ import annotations

import asyncio

from legal_chatbot.legal_evidence.models import (
    AnalysisOrigin,
    AnalyzerOutcome,
    CaseStage,
    LegalCaseContext,
    LegalQuestionAnalysisResult,
    PreferredSourceTier,
    QuestionAnalysis,
    SubIntent,
)
from legal_chatbot.legal_evidence.transitions import advance_case
from legal_chatbot.providers.models import GenerationRequest, OutputVerbosity, ReasoningEffort
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.retrieval.quality_repair.analyzer import AnalyzerUnit, LegalQuestionAnalyzer

from .models import LegalQuestionAnalyzerSettings
from .parser import StrictLegalQuestionAnalysisParser
from .prompt import build_legal_question_analyzer_prompt, legal_question_analysis_output_format


class LLMLegalQuestionAnalyzer:
    """Use an LLM only for proposals; any failure selects deterministic analysis."""

    def __init__(
        self,
        provider: LLMProviderPort | None,
        *,
        settings: LegalQuestionAnalyzerSettings | None = None,
        parser: StrictLegalQuestionAnalysisParser | None = None,
        fallback: LegalQuestionAnalyzer | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings or LegalQuestionAnalyzerSettings()
        self._parser = parser or StrictLegalQuestionAnalysisParser()
        self._fallback = fallback or LegalQuestionAnalyzer()

    async def analyze(self, context: LegalCaseContext) -> LegalQuestionAnalysisResult:
        """Return a bounded proposal or deterministic fallback without exposing provider errors."""

        if not self._settings.enabled:
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_DISABLED)
        if self._provider is None:
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_PROVIDER_UNAVAILABLE)
        try:
            prompt = build_legal_question_analyzer_prompt(context, self._settings)
            generated = await asyncio.wait_for(
                self._provider.generate(
                    GenerationRequest(
                        input_text=prompt,
                        max_output_tokens=self._settings.max_output_tokens,
                        structured_output=legal_question_analysis_output_format(),
                        reasoning_effort=ReasoningEffort.MINIMAL,
                        verbosity=OutputVerbosity.LOW,
                    )
                ),
                timeout=self._settings.timeout_seconds,
            )
        except Exception:
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_PROVIDER_FAILURE)
        try:
            return self._parser.parse(generated.text).to_result()
        except Exception:
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_INVALID_OUTPUT)

    async def analyze_context(self, context: LegalCaseContext) -> LegalCaseContext:
        """Apply P2 output only to a newly received request context."""

        if context.stage is not CaseStage.RECEIVED:
            raise ValueError("legal question analysis requires a received context")
        result = await self.analyze(context)
        return advance_case(
            context,
            CaseStage.ANALYZED,
            question_analysis=result.analysis,
            sub_intents=result.sub_intents,
        )

    def _fallback_result(
        self, context: LegalCaseContext, outcome: AnalyzerOutcome
    ) -> LegalQuestionAnalysisResult:
        observation = self._fallback.analyze(context.question_text)
        first = observation.units[0]
        concepts = tuple(
            dict.fromkeys(
                (*first.concept_query.core_concepts, *first.concept_query.important_noun_phrases)
            )
        )[:8]
        return LegalQuestionAnalysisResult(
            analysis=QuestionAnalysis(
                origin=AnalysisOrigin.DETERMINISTIC_FALLBACK,
                main_intent=observation.intent.value,
                legal_actor=observation.legal_actor,
                legal_action_event=observation.action_event,
                explicit_time=observation.explicit_time,
                legal_topics=observation.legal_topics,
                preferred_source_tiers=self._source_tiers(first.source_binding.value),
                retrieval_concepts=concepts,
                ambiguous=observation.ambiguity.value != "NONE",
            ),
            sub_intents=tuple(self._fallback_sub_intent(unit) for unit in observation.units),
            outcome=outcome,
        )

    @staticmethod
    def _source_tiers(value: str) -> tuple[PreferredSourceTier, ...]:
        if value not in PreferredSourceTier._value2member_map_:
            return ()
        return (PreferredSourceTier(value),)

    @classmethod
    def _fallback_sub_intent(cls, unit: AnalyzerUnit) -> SubIntent:
        intent = unit.intent
        source_binding = unit.source_binding
        concepts = unit.concept_query.core_concepts
        return SubIntent(
            description=intent.value,
            retrieval_concepts=concepts,
            preferred_source_tiers=cls._source_tiers(source_binding.value),
        )


__all__ = ["LLMLegalQuestionAnalyzer"]
