"""Provider-neutral grounded-chat orchestration over narrow ports."""

from time import perf_counter
from typing import Final
from uuid import UUID

from legal_chatbot.chat.config import ChatSettings
from legal_chatbot.chat.errors import ChatError, ChatErrorCode, ProviderOutputFailureClass
from legal_chatbot.chat.models import (
    ANSWER_MAX_CHARS,
    ChatOutcome,
    ChatReasonCode,
    ChatRequest,
    GroundedChatResult,
    GroundingEvidence,
    GroundingEvidenceRequest,
    ProviderAnswer,
)
from legal_chatbot.chat.planner_models import (
    QueryPlannerOutcome,
    QueryPlannerPlan,
    QueryPlannerResult,
    has_protected_identity_drift,
    normalize_planner_text,
    validate_query_plan,
)
from legal_chatbot.chat.policy import (
    apply_temporal_guard,
    refusal_decision,
    retrieval_policy_decision,
)
from legal_chatbot.chat.port import (
    CanonicalAnchorResolverPort,
    GroundingEvidencePort,
    ProviderOutputParserPort,
    QueryPlannerPort,
    RetrievalPort,
)
from legal_chatbot.chat.prompt import build_grounded_prompt
from legal_chatbot.chat.quality_prompt import (
    build_quality_evidence_pack,
    build_quality_grounded_prompt,
)
from legal_chatbot.core.logging import get_logger
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import GenerationRequest, GenerationResult, sanitize_request_id
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.retrieval.models import (
    ResolvedCitation,
    RetrievalRequest,
    RetrievalResult,
    TemporalScope,
)
from legal_chatbot.retrieval.port import CitationResolverPort
from legal_chatbot.retrieval.quality_repair.evidence_pack import QualityRetrievalContext

_IDENTITY_FIELDS: Final = (
    "citation_id",
    "retrieval_run_id",
    "document_chunk_id",
    "document_version_id",
    "document_id",
    "source_provenance_record_id",
    "transport_trust_mode",
    "evidence_trust_label",
)


def validate_chat_provider_compatibility(
    chat_settings: ChatSettings, provider_settings: ProviderSettings
) -> None:
    """Fail fast when the chat contract cannot fit the configured provider bounds."""

    if (
        chat_settings.prompt_max_chars > provider_settings.max_input_chars
        or chat_settings.max_output_tokens > provider_settings.max_output_tokens
        or chat_settings.answer_max_chars > ANSWER_MAX_CHARS
    ):
        raise ValueError("chat and provider bounds are incompatible")


class GroundedChatService:
    """Produce fixed fail-closed results or an answer grounded in revalidated citations."""

    def __init__(
        self,
        retrieval: RetrievalPort,
        grounding_evidence: GroundingEvidencePort,
        citation_resolver: CitationResolverPort,
        provider: LLMProviderPort,
        parser: ProviderOutputParserPort,
        chat_settings: ChatSettings,
        provider_settings: ProviderSettings,
        query_planner: QueryPlannerPort | None = None,
        canonical_anchor_resolver: CanonicalAnchorResolverPort | None = None,
    ) -> None:
        validate_chat_provider_compatibility(chat_settings, provider_settings)
        self._retrieval = retrieval
        self._grounding_evidence = grounding_evidence
        self._citation_resolver = citation_resolver
        self._provider = provider
        self._parser = parser
        self._chat_settings = chat_settings
        self._provider_settings = provider_settings
        self._query_planner = query_planner
        self._canonical_anchor_resolver = canonical_anchor_resolver
        self._logger = get_logger()

    async def respond(self, request: ChatRequest) -> GroundedChatResult:
        """Run the bounded retrieval, generation, and citation-revalidation sequence once."""

        started_at = perf_counter()
        guarded_request = apply_temporal_guard(request)
        (
            planner_result,
            expansion_query,
            expansion_document_ids,
            planner_called,
            planner_started_at,
        ) = await self._plan_retrieval(request, guarded_request)
        try:
            retrieval_result = self._validate_retrieval_result(
                await self._retrieval.retrieve(
                    request=self._retrieval_request(
                        request,
                        guarded_request,
                        expansion_query=expansion_query,
                        expansion_document_ids=expansion_document_ids,
                    )
                )
            )
        except Exception:
            return self._failure(
                ChatReasonCode.RETRIEVAL_FAILURE,
                None,
                provider_called=False,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
            )

        try:
            policy = retrieval_policy_decision(retrieval_result.decision)
        except Exception:
            return self._failure(
                ChatReasonCode.RETRIEVAL_FAILURE,
                None,
                provider_called=False,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
            )

        if policy.outcome is ChatOutcome.CLARIFICATION:
            result = GroundedChatResult(
                outcome=ChatOutcome.CLARIFICATION,
                reason=ChatReasonCode.NO_RESULTS,
                answer=policy.fixed_text or "",
                retrieval_run_id=retrieval_result.retrieval_run_id,
            )
            return self._complete(
                result,
                provider_called=False,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
            )
        if policy.outcome is ChatOutcome.REFUSAL:
            return self._failure(
                policy.reason,
                retrieval_result.retrieval_run_id,
                provider_called=False,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
            )

        try:
            evidence = self._validate_grounding_evidence(
                await self._grounding_evidence.load(
                    GroundingEvidenceRequest(
                        retrieval_run_id=retrieval_result.retrieval_run_id,
                        citation_ids=tuple(
                            candidate.citation_id for candidate in retrieval_result.candidates
                        ),
                    )
                ),
                retrieval_result,
            )
            prompt = self._build_prompt(guarded_request, evidence, retrieval_result)
        except Exception:
            return self._failure(
                ChatReasonCode.GROUNDING_FAILURE,
                retrieval_result.retrieval_run_id,
                provider_called=False,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
            )

        provider_called = True
        try:
            provider_value = await self._provider.generate(
                GenerationRequest(
                    input_text=prompt,
                    max_output_tokens=self._chat_settings.max_output_tokens,
                )
            )
        except ProviderError as error:
            return self._failure(
                ChatReasonCode.PROVIDER_FAILURE,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=self._provider_settings.provider,
                model_name=self._provider_settings.model,
                provider_request_id=sanitize_request_id(error.request_id),
            )
        except Exception:
            return self._failure(
                ChatReasonCode.PROVIDER_FAILURE,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=self._provider_settings.provider,
                model_name=self._provider_settings.model,
            )

        try:
            provider_result = self._validate_generation_result(provider_value)
        except Exception:
            return self._failure(
                ChatReasonCode.INVALID_PROVIDER_OUTPUT,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=self._provider_settings.provider,
                model_name=self._provider_settings.model,
                provider_output_class=ProviderOutputFailureClass.PORT_RESULT_TYPE,
            )

        provider_request_id = sanitize_request_id(provider_result.request_id)
        if len(provider_result.text.encode("utf-8")) > self._provider_settings.max_response_bytes:
            return self._failure(
                ChatReasonCode.INVALID_PROVIDER_OUTPUT,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=provider_result.provider,
                model_name=provider_result.model,
                provider_request_id=provider_request_id,
                provider_output_class=ProviderOutputFailureClass.RESPONSE_BYTES,
            )

        try:
            parsed_answer = self._parser.parse(provider_result.text)
        except ChatError as error:
            return self._failure(
                ChatReasonCode.INVALID_PROVIDER_OUTPUT,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=provider_result.provider,
                model_name=provider_result.model,
                provider_request_id=provider_request_id,
                provider_output_class=(
                    error.provider_output_class
                    if error.code is ChatErrorCode.INVALID_PROVIDER_OUTPUT
                    else ProviderOutputFailureClass.UNKNOWN
                ),
            )
        except Exception:
            return self._failure(
                ChatReasonCode.INVALID_PROVIDER_OUTPUT,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=provider_result.provider,
                model_name=provider_result.model,
                provider_request_id=provider_request_id,
                provider_output_class=ProviderOutputFailureClass.UNKNOWN,
            )

        try:
            answer = self._validate_provider_answer(parsed_answer)
        except Exception:
            output_class = (
                ProviderOutputFailureClass.ANSWER_EMPTY_OR_BOUND
                if isinstance(parsed_answer, ProviderAnswer)
                else ProviderOutputFailureClass.PORT_RESULT_TYPE
            )
            return self._failure(
                ChatReasonCode.INVALID_PROVIDER_OUTPUT,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=provider_result.provider,
                model_name=provider_result.model,
                provider_request_id=provider_request_id,
                provider_output_class=output_class,
            )

        try:
            citations = await self._reresolve_citations(retrieval_result, evidence)
        except Exception:
            return self._failure(
                ChatReasonCode.CITATION_REVALIDATION_FAILURE,
                retrieval_result.retrieval_run_id,
                provider_called=provider_called,
                started_at=started_at,
                planner_result=planner_result,
                planner_called=planner_called,
                planner_started_at=planner_started_at,
                provider_name=provider_result.provider,
                model_name=provider_result.model,
                provider_request_id=provider_request_id,
            )

        result = GroundedChatResult(
            outcome=ChatOutcome.ANSWER,
            reason=ChatReasonCode.ANSWER_GROUNDED,
            answer=answer.answer,
            retrieval_run_id=retrieval_result.retrieval_run_id,
            citations=citations,
            provider=provider_result.provider,
            model=provider_result.model,
            provider_request_id=provider_request_id,
        )
        return self._complete(
            result,
            provider_called=provider_called,
            started_at=started_at,
            planner_result=planner_result,
            planner_called=planner_called,
            planner_started_at=planner_started_at,
        )

    def _retrieval_request(
        self,
        request: ChatRequest,
        guarded_request: ChatRequest,
        *,
        expansion_query: str | None = None,
        expansion_document_ids: tuple[UUID, ...] = (),
    ) -> RetrievalRequest:
        """Construct the sole retrieval request from user text and guarded temporal intent."""

        return RetrievalRequest(
            query=request.retrieval_query or request.question,
            expansion_query=expansion_query,
            expansion_document_ids=expansion_document_ids,
            top_k=self._chat_settings.max_citations,
            temporal_scope=guarded_request.temporal_scope,
        )

    async def _plan_retrieval(
        self, request: ChatRequest, guarded_request: ChatRequest
    ) -> tuple[QueryPlannerResult, str | None, tuple[UUID, ...], bool, float | None]:
        """Use one validated optional expansion only after the temporal fail-closed guard."""

        if guarded_request.temporal_scope is not TemporalScope.NONE:
            return (
                QueryPlannerResult(outcome=QueryPlannerOutcome.SKIPPED_TEMPORAL),
                None,
                (),
                False,
                None,
            )
        if not self._chat_settings.retrieval_planner_enabled or self._query_planner is None:
            return QueryPlannerResult(outcome=QueryPlannerOutcome.DISABLED), None, (), False, None
        if (
            len(normalize_planner_text(request.question))
            > self._chat_settings.retrieval_planner_max_input_chars
            or self._chat_settings.retrieval_planner_max_query_count < 2
        ):
            return (
                QueryPlannerResult(outcome=QueryPlannerOutcome.SKIPPED_INPUT),
                None,
                (),
                False,
                None,
            )
        planner_started_at = perf_counter()
        try:
            value = await self._query_planner.plan(request.question)
            if not isinstance(value, QueryPlannerResult):
                raise ValueError
            planned = QueryPlannerResult.model_validate(value.model_dump())
            if planned.outcome is not QueryPlannerOutcome.PLANNED or planned.plan is None:
                return planned, None, (), True, planner_started_at
            plan = validate_query_plan(
                planned.plan,
                request.question,
                max_phrases=self._chat_settings.retrieval_planner_max_phrases,
                max_expansion_terms=self._chat_settings.retrieval_planner_max_expansion_terms,
            )
            document_ids = await self._resolve_anchor_documents(plan)
            if document_ids is None:
                return (
                    QueryPlannerResult(outcome=QueryPlannerOutcome.UNRESOLVED_ANCHOR),
                    None,
                    (),
                    True,
                    planner_started_at,
                )
            expansion_query = self._build_expansion_query(plan, request.question)
            if expansion_query is None:
                return (
                    QueryPlannerResult(outcome=QueryPlannerOutcome.NO_EXPANSION),
                    None,
                    (),
                    True,
                    planner_started_at,
                )
            return planned, expansion_query, document_ids, True, planner_started_at
        except Exception:
            return (
                QueryPlannerResult(outcome=QueryPlannerOutcome.INVALID_OUTPUT),
                None,
                (),
                True,
                planner_started_at,
            )

    async def _resolve_anchor_documents(self, plan: QueryPlannerPlan) -> tuple[UUID, ...] | None:
        """Require all mentioned anchors to resolve unambiguously; unscoped plans are allowed."""

        if not plan.anchor_mentions:
            return ()
        if self._canonical_anchor_resolver is None:
            return None
        document_ids = await self._canonical_anchor_resolver.resolve(plan.anchor_mentions)
        if (
            document_ids is None
            or not isinstance(document_ids, tuple)
            or not document_ids
            or any(not isinstance(document_id, UUID) for document_id in document_ids)
            or len(set(document_ids)) != len(document_ids)
        ):
            return None
        return document_ids

    def _build_expansion_query(self, plan: QueryPlannerPlan, question: str) -> str | None:
        """Build one controlled lexical query; the provider never supplies query syntax."""

        if self._chat_settings.retrieval_planner_max_query_count < 2:
            return None
        parts = (*plan.key_phrases, *plan.expansion_terms)
        if not parts or any('"' in part or "\\" in part for part in parts):
            return None
        plain_expansion = normalize_planner_text(" ".join(parts))
        original_query = normalize_planner_text(question)
        if (
            not plain_expansion
            or plain_expansion.casefold() == original_query.casefold()
            or has_protected_identity_drift(plain_expansion, original_query)
        ):
            return None
        return " OR ".join(f'"{part}"' for part in parts)

    def _validate_retrieval_result(self, value: object) -> RetrievalResult:
        """Accept only a bounded retrieval result that honors this request's citation bound."""

        if not isinstance(value, RetrievalResult):
            raise ValueError
        result = RetrievalResult.model_validate(value.model_dump())
        if value.quality_context is not None:
            result = result.model_copy(update={"quality_context": value.quality_context})
        if result.candidate_count > self._chat_settings.max_citations:
            raise ValueError
        return result

    def _build_prompt(
        self,
        request: ChatRequest,
        evidence: GroundingEvidence,
        retrieval_result: RetrievalResult,
    ) -> str:
        """Use the structured path only when a validated quality adapter supplied context."""

        context = retrieval_result.quality_context
        if context is None:
            return build_grounded_prompt(request, evidence, self._chat_settings)
        if not isinstance(context, QualityRetrievalContext):
            raise ValueError("quality context is invalid")
        return build_quality_grounded_prompt(
            request, build_quality_evidence_pack(context, evidence), self._chat_settings
        )

    @staticmethod
    def _validate_grounding_evidence(
        value: object, retrieval_result: RetrievalResult
    ) -> GroundingEvidence:
        """Require evidence to be exactly the selected run and ordered candidate identity set."""

        if not isinstance(value, GroundingEvidence):
            raise ValueError
        evidence = GroundingEvidence.model_validate(value.model_dump())
        expected_ids = tuple(candidate.citation_id for candidate in retrieval_result.candidates)
        expected_chunk_ids = tuple(
            candidate.document_chunk_id for candidate in retrieval_result.candidates
        )
        if (
            evidence.retrieval_run_id != retrieval_result.retrieval_run_id
            or tuple(excerpt.citation.citation_id for excerpt in evidence.excerpts) != expected_ids
            or tuple(excerpt.citation.document_chunk_id for excerpt in evidence.excerpts)
            != expected_chunk_ids
        ):
            raise ValueError
        return evidence

    @staticmethod
    def _validate_generation_result(value: object) -> GenerationResult:
        """Normalize malformed port output before its text reaches the parser."""

        if not isinstance(value, GenerationResult):
            raise ValueError
        return GenerationResult.model_validate(value.model_dump())

    def _validate_provider_answer(self, value: object) -> ProviderAnswer:
        """Require parser-owned safe prose and honor the configured answer bound."""

        if not isinstance(value, ProviderAnswer):
            raise ValueError
        answer = ProviderAnswer.model_validate(value.model_dump())
        if len(answer.answer) > self._chat_settings.answer_max_chars:
            raise ValueError
        return answer

    async def _reresolve_citations(
        self, retrieval_result: RetrievalResult, evidence: GroundingEvidence
    ) -> tuple[ResolvedCitation, ...]:
        """Resolve each original citation once, sequentially, and reject identity drift."""

        resolved_citations: list[ResolvedCitation] = []
        for candidate, excerpt in zip(retrieval_result.candidates, evidence.excerpts, strict=True):
            value = await self._citation_resolver.resolve(
                candidate.citation_id, retrieval_result.retrieval_run_id
            )
            if not isinstance(value, ResolvedCitation):
                raise ValueError
            citation = ResolvedCitation.model_validate(value.model_dump())
            if not self._same_citation_identity(citation, excerpt.citation):
                raise ValueError
            resolved_citations.append(citation)
        return tuple(resolved_citations)

    @staticmethod
    def _same_citation_identity(left: ResolvedCitation, right: ResolvedCitation) -> bool:
        """Compare only the immutable server-owned citation identity fields."""

        return all(getattr(left, field) == getattr(right, field) for field in _IDENTITY_FIELDS)

    def _failure(
        self,
        reason: ChatReasonCode,
        retrieval_run_id: UUID | None,
        *,
        provider_called: bool,
        started_at: float,
        planner_result: QueryPlannerResult,
        planner_called: bool,
        planner_started_at: float | None,
        provider_name: str | None = None,
        model_name: str | None = None,
        provider_request_id: str | None = None,
        provider_output_class: ProviderOutputFailureClass | None = None,
    ) -> GroundedChatResult:
        """Return and log one fixed refusal without retaining untrusted failure details."""

        decision = refusal_decision(reason)
        result = GroundedChatResult(
            outcome=ChatOutcome.REFUSAL,
            reason=reason,
            answer=decision.fixed_text or "",
            retrieval_run_id=retrieval_run_id,
        )
        self._log(
            result,
            provider_called=provider_called,
            started_at=started_at,
            planner_result=planner_result,
            planner_called=planner_called,
            planner_started_at=planner_started_at,
            provider_name=provider_name,
            model_name=model_name,
            provider_request_id=provider_request_id,
            provider_output_class=provider_output_class,
        )
        return result

    def _complete(
        self,
        result: GroundedChatResult,
        *,
        provider_called: bool,
        started_at: float,
        planner_result: QueryPlannerResult,
        planner_called: bool,
        planner_started_at: float | None,
    ) -> GroundedChatResult:
        """Log and return the only non-refusal outcomes."""

        self._log(
            result,
            provider_called=provider_called,
            started_at=started_at,
            planner_result=planner_result,
            planner_called=planner_called,
            planner_started_at=planner_started_at,
            provider_name=result.provider,
            model_name=result.model,
            provider_request_id=result.provider_request_id,
        )
        return result

    def _log(
        self,
        result: GroundedChatResult,
        *,
        provider_called: bool,
        started_at: float,
        planner_result: QueryPlannerResult,
        planner_called: bool,
        planner_started_at: float | None,
        provider_name: str | None,
        model_name: str | None,
        provider_request_id: str | None,
        provider_output_class: ProviderOutputFailureClass | None = None,
    ) -> None:
        """Emit only the fixed chat event and approved content-free operational fields."""

        failed = result.outcome is ChatOutcome.REFUSAL
        extra: dict[str, object] = {
            "operation": "grounded_chat",
            "outcome": "failed" if failed else "completed",
            "chat_outcome": result.outcome.value,
            "chat_reason": result.reason.value,
            "chat_provider_called": provider_called,
            "chat_citation_count": len(result.citations),
            "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            "retrieval_planner_enabled": self._chat_settings.retrieval_planner_enabled,
            "retrieval_planner_called": planner_called,
            "retrieval_planner_outcome": planner_result.outcome.value,
            "retrieval_planner_query_count": (
                2 if planner_result.outcome is QueryPlannerOutcome.PLANNED else 1
            ),
        }
        if planner_started_at is not None:
            extra["retrieval_planner_duration_ms"] = round(
                (perf_counter() - planner_started_at) * 1000, 3
            )
        if result.retrieval_run_id is not None:
            extra["retrieval_run_id"] = str(result.retrieval_run_id)
        if provider_name is not None:
            extra["provider"] = provider_name
        if model_name is not None:
            extra["model"] = model_name
        if provider_request_id is not None:
            extra["provider_request_id"] = sanitize_request_id(provider_request_id)
        if provider_output_class is not None:
            extra["chat_provider_output_class"] = provider_output_class.value
        if failed:
            extra["chat_error_code"] = result.reason.value
        self._logger.info(
            "grounded_chat_failed" if failed else "grounded_chat_complete", extra=extra
        )
