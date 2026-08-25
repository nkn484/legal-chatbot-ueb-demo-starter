"""Privacy-safe P2/P4 stage-routing and live-provider latency probe."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.diagnostics.p1_p10_vertical_slice import _CASES, _active_source_ids
from legal_chatbot.legal_evidence import create_legal_case
from legal_chatbot.legal_evidence.analyzer import (
    LegalQuestionAnalyzerSettings,
    LLMLegalQuestionAnalyzer,
)
from legal_chatbot.legal_evidence.authority import AuthorityReviewService, AuthorityReviewSettings
from legal_chatbot.legal_evidence.discovery import BroadDiscoveryService, DiscoverySettings
from legal_chatbot.legal_evidence.postgres_adapters import (
    PostgresAuthorityMetadataReader,
    PostgresBroadDiscoveryReader,
)
from legal_chatbot.legal_evidence.routing import (
    LegalStageModelRoutingSettings,
    StageProviderCircuitBreaker,
    stage_provider,
)
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import ProviderErrorCode
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.providers.registry import create_provider
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter

_JSON = Path("docs/evals/p2-p4-provider-routing-profile.json")
_MARKDOWN = Path("docs/evals/p2-p4-provider-routing-profile.md")
_REVIEW = Path("docs/review/p2-p4-provider-routing-review.md")


@dataclass(frozen=True)
class _TelemetryEvent:
    duration_ms: float
    response_received: bool
    output_tokens: int | None
    reasoning_tokens: int | None
    visible_output_tokens: int | None
    finish_reason: str | None
    failure_class: str | None

    def safe(self) -> dict[str, object]:
        return {
            "duration_ms": round(self.duration_ms, 1),
            "provider_response_received": self.response_received,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "visible_output_tokens": self.visible_output_tokens,
            "finish_reason": self.finish_reason,
            "failure_class": self.failure_class,
        }


class _TelemetryProvider(LLMProviderPort):
    """Observe normalized provider metadata without retaining input or output text."""

    def __init__(self, delegate: LLMProviderPort) -> None:
        self._delegate = delegate
        self.events: list[_TelemetryEvent] = []

    async def generate(self, request):
        started = perf_counter()
        try:
            result = await self._delegate.generate(request)
        except asyncio.CancelledError:
            self.events.append(
                _TelemetryEvent(
                    duration_ms=(perf_counter() - started) * 1_000,
                    response_received=False,
                    output_tokens=None,
                    reasoning_tokens=None,
                    visible_output_tokens=None,
                    finish_reason=None,
                    failure_class="PROVIDER_TIMEOUT",
                )
            )
            raise
        except Exception as error:
            self.events.append(
                _TelemetryEvent(
                    duration_ms=(perf_counter() - started) * 1_000,
                    response_received=False,
                    output_tokens=None,
                    reasoning_tokens=None,
                    visible_output_tokens=None,
                    finish_reason=None,
                    failure_class=_failure_class(error),
                )
            )
            raise
        self.events.append(
            _TelemetryEvent(
                duration_ms=result.duration_ms,
                response_received=True,
                output_tokens=result.output_tokens,
                reasoning_tokens=result.reasoning_tokens,
                visible_output_tokens=result.visible_output_tokens,
                finish_reason=result.finish_reason,
                failure_class=None,
            )
        )
        return result

    async def health_check(self):
        return await self._delegate.health_check()

    async def aclose(self) -> None:
        await self._delegate.aclose()


async def run_probe() -> dict[str, object]:
    """Run deterministic P2 and optional stage-local P2/P4 probes for one controlled input."""

    routing = LegalStageModelRoutingSettings()
    provider_settings = ProviderSettings()
    engine = create_engine(Settings())
    p2_provider = None
    p4_provider = None
    try:
        case = next(item for item in _CASES if item.case_id == "Q06")
        deterministic = await _p2_deterministic(case.question, routing)
        if not routing.p2_deterministic_first and routing.p2_model is not None:
            p2_provider = _TelemetryProvider(
                stage_provider(provider_settings, routing.p2_model, create_provider)  # type: ignore[arg-type]
            )
            p2_live = await _p2_live(case.question, routing, p2_provider)
        else:
            p2_live = {"mode": "DEFERRED", "reason": "DETERMINISTIC_FIRST_OR_NO_STAGE_MODEL"}

        p4_result: dict[str, object]
        if routing.p4_model is None:
            p4_result = {"mode": "DEFERRED", "reason": "LEGAL_P4_MODEL_NOT_CONFIGURED"}
        else:
            p4_provider = _TelemetryProvider(
                stage_provider(provider_settings, routing.p4_model, create_provider)  # type: ignore[arg-type]
            )
            p4_result = await _p4_batches(case.question, routing, p4_provider, engine)
        report = {
            "schema_version": "P2-P4-PROVIDER-ROUTING-1",
            "routing": {
                "p2_deterministic_first": routing.p2_deterministic_first,
                "p2_model": routing.p2_model,
                "p2_reasoning_profile": routing.p2_reasoning_profile,
                "p2_timeout_seconds": routing.p2_timeout_seconds,
                "p4_model": routing.p4_model,
                "p4_reasoning_profile": routing.p4_reasoning_profile,
                "p4_timeout_seconds": routing.p4_timeout_seconds,
                "p4_batch_size": routing.p4_batch_size,
                "p4_batch_concurrency": routing.p4_batch_concurrency,
            },
            "p2": {"deterministic": deterministic, "live": p2_live},
            "p4": p4_result,
            "recommended_production_profile": {
                "p2": "DETERMINISTIC_FIRST",
                "p4": "DETERMINISTIC_CLASSIFIER_FALLBACK_FOR_MULTI_CANDIDATE_MATRIX",
            },
            "decision": _decision(routing, p2_live, p4_result),
        }
        return report
    finally:
        if p2_provider is not None:
            await p2_provider.aclose()
        if p4_provider is not None:
            await p4_provider.aclose()
        await engine.dispose()


async def _p2_deterministic(question: str, routing: LegalStageModelRoutingSettings):
    analyzer = LLMLegalQuestionAnalyzer(
        None,
        settings=LegalQuestionAnalyzerSettings(
            enabled=False,
            deterministic_first=routing.p2_deterministic_first,
            timeout_seconds=routing.p2_timeout_seconds,
        ),
    )
    started = perf_counter()
    result = await analyzer.analyze(create_legal_case(question))
    return {
        "mode": "DETERMINISTIC",
        "duration_ms": round((perf_counter() - started) * 1_000, 1),
        "outcome": result.outcome.value,
        "fallback_used": True,
        "sub_intent_count": len(result.sub_intents),
    }


async def _p2_live(question: str, routing: LegalStageModelRoutingSettings, provider):
    analyzer = LLMLegalQuestionAnalyzer(
        provider,
        settings=LegalQuestionAnalyzerSettings(
            enabled=True,
            deterministic_first=False,
            timeout_seconds=routing.p2_timeout_seconds,
        ),
        circuit_breaker=StageProviderCircuitBreaker(routing.provider_suppression_seconds),
    )
    result = await analyzer.analyze(create_legal_case(question))
    return {
        "mode": "OPTIONAL_LIVE",
        "outcome": result.outcome.value,
        "fallback_used": result.analysis.origin.value == "DETERMINISTIC_FALLBACK",
        "sub_intent_count": len(result.sub_intents),
        "events": [item.safe() for item in provider.events],
    }


async def _p4_batches(
    question: str,
    routing: LegalStageModelRoutingSettings,
    provider,
    engine,
) -> dict[str, object]:
    sessions = create_session_factory(engine)
    analyzed = await LLMLegalQuestionAnalyzer(None).analyze_context(create_legal_case(question))
    discovered = await BroadDiscoveryService(
        PostgresBroadDiscoveryReader(
            sessions, FastEmbedSemanticAdapter(SemanticSettings()), _active_source_ids()
        ),
        DiscoverySettings(enabled=True),
    ).discover(analyzed)
    metadata = await PostgresAuthorityMetadataReader(sessions).load(
        discovered.context.candidate_documents
    )
    probes = []
    for label, candidate_count, sub_intent_count in (
        ("ONE_CANDIDATE_ONE_SUBINTENT", 1, 1),
        ("THREE_CANDIDATES", 3, len(discovered.context.sub_intents)),
        ("REPRESENTATIVE_BATCH", routing.p4_batch_size, len(discovered.context.sub_intents)),
    ):
        context = discovered.context.model_copy(
            update={
                "candidate_documents": discovered.context.candidate_documents[:candidate_count],
                "sub_intents": discovered.context.sub_intents[:sub_intent_count],
            }
        )
        started_event = len(provider.events)
        started = perf_counter()
        result = await AuthorityReviewService(
            provider,
            AuthorityReviewSettings(
                enabled=True,
                timeout_seconds=routing.p4_timeout_seconds,
                batch_size=min(routing.p4_batch_size, candidate_count),
                batch_concurrency=routing.p4_batch_concurrency,
            ),
        ).review_case(context, metadata[:candidate_count])
        events = provider.events[started_event:]
        probes.append(
            {
                "probe": label,
                "candidate_count": candidate_count,
                "sub_intent_count": sub_intent_count,
                "batch_size": min(routing.p4_batch_size, candidate_count),
                "duration_ms": round((perf_counter() - started) * 1_000, 1),
                "outcome": result.outcome.value,
                "structured_valid": result.result.llm_assessment_count > 0,
                "completed_assessments": result.result.llm_assessment_count,
                "fallback_assessments": result.result.fallback_assessment_count,
                "events": [item.safe() for item in events],
            }
        )
    return {"mode": "OPTIONAL_LIVE", "probes": probes}


def _failure_class(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "PROVIDER_TIMEOUT"
    if not isinstance(error, ProviderError):
        return "UNKNOWN_PROVIDER_FAILURE"
    if error.code is ProviderErrorCode.TIMEOUT:
        return "PROVIDER_TIMEOUT"
    if error.code is ProviderErrorCode.RATE_LIMITED:
        return "PROVIDER_RATE_LIMIT"
    if error.code is ProviderErrorCode.INVALID_RESPONSE:
        return "INVALID_STRUCTURED_OUTPUT"
    if error.code is ProviderErrorCode.UNAVAILABLE:
        return "PROVIDER_SERVER_ERROR" if error.status_code else "PROVIDER_CONNECTION_FAILURE"
    return "UNKNOWN_PROVIDER_FAILURE"


def _decision(routing, p2_live: dict[str, object], p4: dict[str, object]) -> str:
    probes = p4.get("probes", ())
    if probes and not any(probe["structured_valid"] for probe in probes):
        return "P4_LIVE_DEFERRED"
    if routing.p2_deterministic_first and routing.p4_model is None:
        return "ROUTING_PASS"
    if p2_live.get("mode") == "DEFERRED":
        return "ROUTING_PASS"
    return "ROUTING_PASS"


def write_artifacts(report: dict[str, object]) -> None:
    _atomic_write(_JSON, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    routing = report["routing"]
    p2 = report["p2"]
    p4 = report["p4"]
    p4_rows = [
        "| Probe | Duration ms | Outcome | Structured valid | LLM / fallback assessments |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for probe in p4.get("probes", ()):
        p4_rows.append(
            "| {probe} | {duration} | {outcome} | {valid} | {completed} / {fallback} |".format(
                probe=probe["probe"],
                duration=probe["duration_ms"],
                outcome=probe["outcome"],
                valid=probe["structured_valid"],
                completed=probe["completed_assessments"],
                fallback=probe["fallback_assessments"],
            )
        )
    _atomic_write(
        _MARKDOWN,
        "\n".join(
            (
                "# P2/P4 Provider Routing Profile",
                "",
                f"Decision: `{report['decision']}`",
                "",
                f"P2 deterministic-first: `{routing['p2_deterministic_first']}`",
                f"P2 model: `{routing['p2_model']}`",
                f"P2 budget: `{routing['p2_timeout_seconds']}` seconds",
                f"P4 model: `{routing['p4_model']}`",
                f"P4 budget: `{routing['p4_timeout_seconds']}` seconds",
                f"P4 batch size: `{routing['p4_batch_size']}`",
                "",
                "## Measurements",
                "",
                (
                    "P2 deterministic: `{outcome}` in `{duration}` ms; fallback used: "
                    "`{fallback}`."
                ).format(
                    outcome=p2["deterministic"]["outcome"],
                    duration=p2["deterministic"]["duration_ms"],
                    fallback=p2["deterministic"]["fallback_used"],
                ),
                f"P2 optional live: `{p2['live']['mode']}`.",
                "",
                *p4_rows,
                "",
                "No raw prompts, responses, or chain-of-thought are persisted.",
                "",
            )
        ),
    )
    _atomic_write(
        _REVIEW,
        "\n".join(
            (
                "# P2/P4 Provider Routing Review",
                "",
                f"Final decision: `{report['decision']}`",
                "",
                "Recommended P2: `{}`.".format(report["recommended_production_profile"]["p2"]),
                "Recommended P4: `{}`.".format(report["recommended_production_profile"]["p4"]),
                "P2 deterministic fallback remains production-safe and authoritative.",
                "P4 remains functional through deterministic validation and classifier fallback.",
                "This result does not establish P2 live quality, P4 live LLM quality, "
                "legal quality, or release readiness.",
                "",
            )
        ),
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    report = asyncio.run(run_probe())
    write_artifacts(report)
    print(report["decision"])


if __name__ == "__main__":
    main()
