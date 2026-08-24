"""Provider-neutral, one-shot LLM query-planner orchestration."""

import asyncio
import re

from legal_chatbot.chat.config import ChatSettings
from legal_chatbot.chat.planner_models import (
    PLANNER_MAX_RESPONSE_BYTES,
    QueryPlannerOutcome,
    QueryPlannerResult,
)
from legal_chatbot.chat.planner_parser import StrictQueryPlannerParser
from legal_chatbot.chat.planner_prompt import build_query_planner_prompt
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.models import GenerationRequest, GenerationResult
from legal_chatbot.providers.port import LLMProviderPort

_MEANINGFUL_TOKEN = re.compile(r"[^\W_]{2,}", re.UNICODE)


class LLMQueryPlanner:
    """Make at most one bounded provider call and convert every failure to a safe result."""

    def __init__(
        self,
        provider: LLMProviderPort,
        settings: ChatSettings,
        provider_settings: ProviderSettings,
        *,
        parser: StrictQueryPlannerParser | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._provider_settings = provider_settings
        self._parser = parser or StrictQueryPlannerParser()

    async def plan(self, question: str) -> QueryPlannerResult:
        """Return a validated plan or a content-free graceful-degradation outcome."""

        if (
            not isinstance(question, str)
            or len(question) > self._settings.retrieval_planner_max_input_chars
            or not _MEANINGFUL_TOKEN.search(question)
        ):
            return QueryPlannerResult(outcome=QueryPlannerOutcome.SKIPPED_INPUT)
        try:
            prompt = build_query_planner_prompt(question)
            if (
                len(prompt) > self._provider_settings.max_input_chars
                or self._settings.retrieval_planner_max_output_tokens
                > self._provider_settings.max_output_tokens
            ):
                return QueryPlannerResult(outcome=QueryPlannerOutcome.SKIPPED_INPUT)
            async with asyncio.timeout(self._settings.retrieval_planner_timeout_seconds):
                provider_result = await self._provider.generate(
                    GenerationRequest(
                        input_text=prompt,
                        max_output_tokens=self._settings.retrieval_planner_max_output_tokens,
                    )
                )
        except Exception:
            return QueryPlannerResult(outcome=QueryPlannerOutcome.PROVIDER_FAILURE)
        try:
            if not isinstance(provider_result, GenerationResult):
                raise ValueError
            if len(provider_result.text.encode("utf-8")) > min(
                PLANNER_MAX_RESPONSE_BYTES,
                self._provider_settings.max_response_bytes,
            ):
                raise ValueError
            plan = self._parser.parse(
                provider_result.text,
                question,
                max_phrases=self._settings.retrieval_planner_max_phrases,
                max_expansion_terms=self._settings.retrieval_planner_max_expansion_terms,
            )
            return QueryPlannerResult(outcome=QueryPlannerOutcome.PLANNED, plan=plan)
        except Exception:
            return QueryPlannerResult(outcome=QueryPlannerOutcome.INVALID_OUTPUT)
