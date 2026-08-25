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
)
from legal_chatbot.legal_evidence.routing import StageProviderCircuitBreaker
from legal_chatbot.legal_evidence.transitions import advance_case
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    OutputVerbosity,
    ProviderErrorCode,
    ReasoningEffort,
)
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.retrieval.quality_repair.analyzer import LegalQuestionAnalyzer

from .deterministic import DeterministicMaterialDecomposer
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
        material_decomposer: DeterministicMaterialDecomposer | None = None,
        circuit_breaker: StageProviderCircuitBreaker | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings or LegalQuestionAnalyzerSettings()
        self._parser = parser or StrictLegalQuestionAnalysisParser()
        self._fallback = fallback or LegalQuestionAnalyzer()
        self._material_decomposer = material_decomposer or DeterministicMaterialDecomposer()
        self._circuit_breaker = circuit_breaker or StageProviderCircuitBreaker()

    async def analyze(self, context: LegalCaseContext) -> LegalQuestionAnalysisResult:
        """Return a bounded proposal or deterministic fallback without exposing provider errors."""

        if not self._settings.enabled or self._settings.deterministic_first:
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_DISABLED)
        if self._provider is None:
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_PROVIDER_UNAVAILABLE)
        if self._circuit_breaker.is_suppressed("P2"):
            return self._fallback_result(context, AnalyzerOutcome.FALLBACK_PROVIDER_SUPPRESSED)
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
        except Exception as error:
            self._record_failure()
            return self._fallback_result(context, self._failure_outcome(error))
        try:
            result = self._parser.parse(generated.text).to_result()
            if self._material_decomposer.materially_multidimensional(context.question_text) and len(
                result.sub_intents
            ) == 1:
                return self._fallback_result(
                    context, AnalyzerOutcome.FALLBACK_INSUFFICIENT_DECOMPOSITION
                )
            self._circuit_breaker.record_success("P2")
            return result
        except Exception:
            self._record_failure()
            return self._fallback_result(
                context, AnalyzerOutcome.FALLBACK_INVALID_STRUCTURED_OUTPUT
            )

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
            sub_intents=self._material_decomposer.decompose(
                context.question_text,
                actor_scope=observation.legal_actor,
                preferred_source_tiers=self._source_tiers(first.source_binding.value),
            ),
            outcome=outcome,
        )

    def _record_failure(self) -> None:
        self._circuit_breaker.record_failure("P2")

    @staticmethod
    def _failure_outcome(error: Exception) -> AnalyzerOutcome:
        if isinstance(error, asyncio.TimeoutError):
            return AnalyzerOutcome.FALLBACK_PROVIDER_TIMEOUT
        if not isinstance(error, ProviderError):
            return AnalyzerOutcome.FALLBACK_PROVIDER_FAILURE
        if error.code is ProviderErrorCode.TIMEOUT:
            return AnalyzerOutcome.FALLBACK_PROVIDER_TIMEOUT
        if error.code is ProviderErrorCode.RATE_LIMITED:
            return AnalyzerOutcome.FALLBACK_PROVIDER_RATE_LIMIT
        if error.code is ProviderErrorCode.UNAVAILABLE:
            return AnalyzerOutcome.FALLBACK_PROVIDER_CONNECTION_FAILURE
        if error.code is ProviderErrorCode.INVALID_RESPONSE:
            return AnalyzerOutcome.FALLBACK_INVALID_STRUCTURED_OUTPUT
        return AnalyzerOutcome.FALLBACK_PROVIDER_SERVER_ERROR

    @staticmethod
    def _source_tiers(value: str) -> tuple[PreferredSourceTier, ...]:
        if value not in PreferredSourceTier._value2member_map_:
            return ()
        return (PreferredSourceTier(value),)

__all__ = ["LLMLegalQuestionAnalyzer"]
