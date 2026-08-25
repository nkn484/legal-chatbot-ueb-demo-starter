"""P1-P10 request-scoped vertical-slice composition.

This profile intentionally freezes P2 on the deterministic fallback and keeps
P11 out of the request path.  It is a diagnostic integration profile, not a
legal-quality release profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.legal_evidence import CaseStage, LegalCaseContext, create_legal_case
from legal_chatbot.legal_evidence.analyzer import (
    LegalQuestionAnalyzerSettings,
    LLMLegalQuestionAnalyzer,
)
from legal_chatbot.legal_evidence.authority import AuthorityReviewService, AuthorityReviewSettings
from legal_chatbot.legal_evidence.completeness import (
    CompletenessReviewService,
    CompletenessSettings,
)
from legal_chatbot.legal_evidence.composition import DeterministicEvidenceBoundComposer
from legal_chatbot.legal_evidence.discovery import BroadDiscoveryService, DiscoverySettings
from legal_chatbot.legal_evidence.pinpoint import PinpointEvidenceService, PinpointSettings
from legal_chatbot.legal_evidence.postgres_adapters import (
    AuthorityMetadataReaderPort,
    PostgresAuthorityMetadataReader,
    PostgresBroadDiscoveryReader,
    PostgresCompositionEvidenceReader,
    PostgresPinpointEvidenceReader,
    PostgresTargetedRepairReader,
)
from legal_chatbot.legal_evidence.relations import (
    RelationInvestigationService,
    RelationInvestigationSettings,
)
from legal_chatbot.legal_evidence.repair import RepairSettings, TargetedRepairService
from legal_chatbot.legal_evidence.selection import (
    CoverageFirstEvidenceSelector,
    EvidenceSelectionSettings,
)
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.semantic.ports import SemanticEmbeddingPort


@dataclass(frozen=True)
class VerticalSliceTrace:
    """Per-request phase outputs retained only for diagnostic artifact generation."""

    context: LegalCaseContext
    discovery: object
    authority: object
    relations: object
    pinpoint: object
    coverage_before_repair: object
    repair: object
    coverage_after_repair: object | None
    selection: object
    composition: object


class P1P10VerticalSliceInvestigator:
    """Advance exactly one immutable context through P2-P10 without P11."""

    def __init__(
        self,
        *,
        analyzer: LLMLegalQuestionAnalyzer,
        discovery: BroadDiscoveryService,
        authority_metadata: AuthorityMetadataReaderPort,
        authority: AuthorityReviewService,
        relations: RelationInvestigationService,
        pinpoint: PinpointEvidenceService,
        completeness: CompletenessReviewService,
        repair: TargetedRepairService,
        selector: CoverageFirstEvidenceSelector,
        composer: DeterministicEvidenceBoundComposer,
    ) -> None:
        self._analyzer = analyzer
        self._discovery = discovery
        self._authority_metadata = authority_metadata
        self._authority = authority
        self._relations = relations
        self._pinpoint = pinpoint
        self._completeness = completeness
        self._repair = repair
        self._selector = selector
        self._composer = composer

    async def investigate(self, question: str) -> LegalCaseContext:
        """Run the vertical slice and return only the completed request context."""

        return (await self.investigate_with_trace(question)).context

    async def investigate_with_trace(self, question: str) -> VerticalSliceTrace:
        """Run the same request path while exposing phase outputs for diagnostics."""

        context = await self._analyzer.analyze_context(create_legal_case(question))
        discovery = await self._discovery.discover(context)
        metadata = await self._authority_metadata.load(discovery.context.candidate_documents)
        authority = await self._authority.review_case(discovery.context, metadata)
        relations = await self._relations.investigate_context(authority.context)
        pinpoint = await self._pinpoint.read_context(relations.context)
        context, coverage_before = await self._completeness.review_context(pinpoint.context)
        context, repair = await self._repair.repair_context(context)
        coverage_after = None
        if repair.repair_executed:
            context, coverage_after = await self._completeness.review_context(context)
        context, selection = self._selector.select_context(context)
        context, composition = await self._composer.compose_context(context)
        if context.stage is not CaseStage.ANSWER_DRAFTED:
            raise RuntimeError("P1_P10_VERTICAL_SLICE_DID_NOT_REACH_DRAFT")
        return VerticalSliceTrace(
            context=context,
            discovery=discovery,
            authority=authority,
            relations=relations,
            pinpoint=pinpoint,
            coverage_before_repair=coverage_before,
            repair=repair,
            coverage_after_repair=coverage_after,
            selection=selection,
            composition=composition,
        )


def build_p1_p10_vertical_slice(
    session_factory: async_sessionmaker[AsyncSession],
    semantic_embedder: SemanticEmbeddingPort,
    active_source_ids: tuple[str, ...],
    *,
    p4_provider: LLMProviderPort | None = None,
    p4_llm_enabled: bool = False,
    p2_provider: LLMProviderPort | None = None,
    p2_settings: LegalQuestionAnalyzerSettings | None = None,
    p4_settings: AuthorityReviewSettings | None = None,
) -> P1P10VerticalSliceInvestigator:
    """Build the fixed diagnostic profile with real PostgreSQL P3/P6/P8 readers."""

    discovery_reader = PostgresBroadDiscoveryReader(
        session_factory, semantic_embedder, active_source_ids
    )
    pinpoint_reader = PostgresPinpointEvidenceReader(session_factory)
    return P1P10VerticalSliceInvestigator(
        analyzer=LLMLegalQuestionAnalyzer(
            p2_provider,
            settings=p2_settings or LegalQuestionAnalyzerSettings(enabled=False),
        ),
        discovery=BroadDiscoveryService(discovery_reader, DiscoverySettings(enabled=True)),
        authority_metadata=PostgresAuthorityMetadataReader(session_factory),
        authority=AuthorityReviewService(
            p4_provider,
            p4_settings or AuthorityReviewSettings(enabled=p4_llm_enabled),
        ),
        relations=RelationInvestigationService(None, RelationInvestigationSettings(enabled=False)),
        pinpoint=PinpointEvidenceService(pinpoint_reader, PinpointSettings(enabled=True)),
        completeness=CompletenessReviewService(None, CompletenessSettings(enabled=False)),
        repair=TargetedRepairService(
            PostgresTargetedRepairReader(pinpoint_reader), RepairSettings(enabled=True)
        ),
        selector=CoverageFirstEvidenceSelector(EvidenceSelectionSettings(enabled=True)),
        composer=DeterministicEvidenceBoundComposer(PostgresCompositionEvidenceReader(session_factory)),
    )


__all__ = [
    "P1P10VerticalSliceInvestigator",
    "VerticalSliceTrace",
    "build_p1_p10_vertical_slice",
]
