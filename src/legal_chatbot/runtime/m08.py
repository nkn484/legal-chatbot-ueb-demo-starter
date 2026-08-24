"""Production composition root for the M08 Official Zalo Bot channel lane."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from legal_chatbot.channels.adapters.official_bot import OfficialZaloBotChannelPort
from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.formatter import ChannelFormatter
from legal_chatbot.channels.port import (
    ChannelBindingRepositoryPort,
    ChannelConversationPort,
    ChannelIngressPort,
    ChannelOutboundRepositoryPort,
    ChannelPort,
)
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry
from legal_chatbot.channels.repository import (
    PostgresChannelBindingRepository,
    PostgresChannelOutboundRepository,
)
from legal_chatbot.channels.service import ChannelService
from legal_chatbot.chat.config import ChatSettings
from legal_chatbot.chat.parser import StrictProviderJsonParser
from legal_chatbot.chat.planner_service import LLMQueryPlanner
from legal_chatbot.chat.port import (
    CanonicalAnchorResolverPort,
    GroundingEvidencePort,
    ProviderOutputParserPort,
    QueryPlannerPort,
    RetrievalPort,
)
from legal_chatbot.chat.service import GroundedChatService
from legal_chatbot.conversation.config import ConversationSettings
from legal_chatbot.conversation.port import ConversationRepositoryPort, GroundedChatPort
from legal_chatbot.conversation.repository import PostgresConversationRepository
from legal_chatbot.conversation.service import ConversationService
from legal_chatbot.db.session import create_session_factory
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.documents.canonical_anchor_resolver import PostgresCanonicalAnchorResolver
from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.grounding_evidence import PostgresGroundingEvidenceAdapter
from legal_chatbot.documents.hybrid_retrieval_repository import PostgresHybridRetrievalRepository
from legal_chatbot.documents.metadata_repair_repository import (
    PostgresMetadataRepairRetrievalRepository,
)
from legal_chatbot.documents.quality_candidate_reader import PostgresQualityCandidateReader
from legal_chatbot.documents.quality_retrieval_pipeline import LegalQualityCandidatePipeline
from legal_chatbot.documents.quality_retrieval_repository import PostgresQualityRetrievalRepository
from legal_chatbot.documents.reranked_semantic_repository import PostgresRerankedSemanticRepository
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.providers.registry import create_provider
from legal_chatbot.reranking.config import RerankerSettings
from legal_chatbot.reranking.fastembed_adapter import FastEmbedRerankerAdapter
from legal_chatbot.reranking.port import RerankerPort
from legal_chatbot.retrieval.config import RetrievalSettings
from legal_chatbot.retrieval.port import CitationResolverPort, RetrievalRepositoryPort
from legal_chatbot.retrieval.quality_repair.analyzer import LegalQuestionAnalyzer
from legal_chatbot.retrieval.quality_repair.models import SourceId
from legal_chatbot.retrieval.quality_repair.strategy import materialize_strategy
from legal_chatbot.retrieval.service import RetrievalService
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter
from legal_chatbot.semantic.ports import SemanticEmbeddingPort
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.registry import load_registry


def _active_source_ids_from_registry() -> tuple[str, ...]:
    """Load the validated registry once and return its bounded active source IDs."""

    source_settings = SourceSettings()
    registry = load_registry(source_settings.registry_path)
    active_source_ids = tuple(
        source.id for source in registry.systems if source.lifecycle == "ACTIVE"
    )
    corpus_settings = DemoCorpusSettings()
    if corpus_settings.enabled:
        approved_snapshot_ids = corpus_settings.retrieval_source_ids()
        registry_ids = {source.id for source in registry.systems}
        if any(source_id not in registry_ids for source_id in approved_snapshot_ids):
            raise ValueError("M08_DEMO_CORPUS_SOURCE_NOT_REGISTERED")
        active_source_ids = tuple(
            source.id
            for source in registry.systems
            if source.id in set((*active_source_ids, *approved_snapshot_ids))
        )
    if not active_source_ids:
        raise ValueError("M08_ACTIVE_SOURCE_REGISTRY_REQUIRED")
    return active_source_ids


def _registry_canonical_anchor_resolver_factory(
    session_factory: async_sessionmaker[AsyncSession], active_source_ids: tuple[str, ...]
) -> CanonicalAnchorResolverPort:
    """Create the resolver with the runtime's already validated active source set."""

    return PostgresCanonicalAnchorResolver(session_factory, active_source_ids)


async def _semantic_coverage_complete(
    session_factory: async_sessionmaker[AsyncSession], active_source_ids: tuple[str, ...]
) -> bool:
    """Check offline semantic coverage before constructing a model-backed repository."""

    return await PostgresHybridRetrievalRepository.coverage_complete_for(
        session_factory, active_source_ids
    )


@dataclass
class ChannelRuntime:
    """Owned channel composition and its narrow ingress seam."""

    ingress: ChannelIngressPort = field(repr=False)
    provider: LLMProviderPort = field(repr=False)
    channel: ChannelPort = field(repr=False)
    recipients: OfficialBotRecipientRegistry = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    async def aclose(self) -> None:
        """Close owned resources once, always attempting the channel before provider."""

        if self._closed:
            return
        self._closed = True
        failed = False
        self.recipients.clear()
        try:
            await self.channel.aclose()
        except Exception:
            failed = True
        try:
            await self.provider.aclose()
        except Exception:
            failed = True
        if failed:
            raise RuntimeError("M08_RUNTIME_CLOSE_FAILED")


async def build_m08_runtime(
    engine: AsyncEngine,
    channel_settings: ChannelSettings,
    *,
    provider_settings: ProviderSettings | None = None,
    chat_settings: ChatSettings | None = None,
    conversation_settings: ConversationSettings | None = None,
    provider_factory: Callable[[ProviderSettings], LLMProviderPort] = create_provider,
    session_factory_factory: Callable[[AsyncEngine], async_sessionmaker[AsyncSession]] = (
        create_session_factory
    ),
    retrieval_settings: RetrievalSettings | None = None,
    lexical_repository_factory: Callable[
        [async_sessionmaker[AsyncSession], tuple[str, ...]], RetrievalRepositoryPort
    ] | None = None,
    semantic_settings: SemanticSettings | None = None,
    semantic_embedder_factory: Callable[[SemanticSettings], SemanticEmbeddingPort] = (
        FastEmbedSemanticAdapter
    ),
    hybrid_repository_factory: Callable[
        [
            async_sessionmaker[AsyncSession],
            tuple[str, ...],
            SemanticEmbeddingPort,
        ],
        RetrievalRepositoryPort,
    ] | None = None,
    semantic_coverage_checker: Callable[
        [async_sessionmaker[AsyncSession], tuple[str, ...]], Awaitable[bool]
    ] = _semantic_coverage_complete,
    reranker_settings: RerankerSettings | None = None,
    reranker_factory: Callable[[RerankerSettings], RerankerPort] = FastEmbedRerankerAdapter,
    reranked_repository_factory: Callable[
        [async_sessionmaker[AsyncSession], tuple[str, ...], SemanticEmbeddingPort, RerankerPort],
        RetrievalRepositoryPort,
    ] | None = None,
    metadata_repair_repository_factory: Callable[
        [async_sessionmaker[AsyncSession], tuple[str, ...], SemanticEmbeddingPort, RerankerPort],
        RetrievalRepositoryPort,
    ] | None = None,
    retrieval_service_factory: Callable[
        [RetrievalRepositoryPort], RetrievalPort
    ] = RetrievalService,
    grounding_evidence_factory: Callable[
        [async_sessionmaker[AsyncSession], ChatSettings], GroundingEvidencePort
    ] = (PostgresGroundingEvidenceAdapter),
    citation_resolver_factory: Callable[
        [async_sessionmaker[AsyncSession]], CitationResolverPort
    ] = PostgresCitationResolver,
    parser_factory: Callable[[], ProviderOutputParserPort] = StrictProviderJsonParser,
    query_planner_factory: Callable[
        [LLMProviderPort, ChatSettings, ProviderSettings], QueryPlannerPort
    ] = LLMQueryPlanner,
    canonical_anchor_resolver_factory: Callable[
        [async_sessionmaker[AsyncSession], tuple[str, ...]], CanonicalAnchorResolverPort
    ] = _registry_canonical_anchor_resolver_factory,
    grounded_chat_service_factory: Callable[
        [
            RetrievalPort,
            GroundingEvidencePort,
            CitationResolverPort,
            LLMProviderPort,
            ProviderOutputParserPort,
            ChatSettings,
            ProviderSettings,
            QueryPlannerPort | None,
            CanonicalAnchorResolverPort | None,
        ],
        GroundedChatPort,
    ] = GroundedChatService,
    conversation_repository_factory: Callable[
        [async_sessionmaker[AsyncSession], ConversationSettings], ConversationRepositoryPort
    ] = (PostgresConversationRepository),
    conversation_service_factory: Callable[
        [ConversationRepositoryPort, GroundedChatPort, CitationResolverPort, ConversationSettings],
        ChannelConversationPort,
    ] = ConversationService,
    binding_repository_factory: Callable[
        [async_sessionmaker[AsyncSession], ChannelSettings], ChannelBindingRepositoryPort
    ] = (PostgresChannelBindingRepository),
    outbound_repository_factory: Callable[
        [async_sessionmaker[AsyncSession], ChannelSettings], ChannelOutboundRepositoryPort
    ] = (PostgresChannelOutboundRepository),
    formatter_factory: Callable[[ChannelSettings], ChannelFormatter] = ChannelFormatter,
    recipient_registry_factory: Callable[[], OfficialBotRecipientRegistry] = (
        OfficialBotRecipientRegistry
    ),
    channel_factory: Callable[[ChannelSettings, OfficialBotRecipientRegistry], ChannelPort] = (
        OfficialZaloBotChannelPort
    ),
    channel_service_factory: Callable[..., ChannelIngressPort] = ChannelService,
) -> ChannelRuntime | None:
    """Build the complete enabled graph without retaining a database session."""

    if not channel_settings.enabled:
        return None

    try:
        resolved_provider_settings = (
            provider_settings if provider_settings is not None else ProviderSettings()  # type: ignore[call-arg]
        )
        resolved_chat_settings = chat_settings if chat_settings is not None else ChatSettings()
        resolved_conversation_settings = (
            conversation_settings if conversation_settings is not None else ConversationSettings()
        )
        resolved_retrieval_settings = (
            retrieval_settings if retrieval_settings is not None else RetrievalSettings()
        )
        active_source_ids = _active_source_ids_from_registry()
    except Exception:
        raise RuntimeError("M08_RUNTIME_CONSTRUCTION_FAILED") from None
    if resolved_provider_settings.provider != "shineshop":
        raise ValueError("M08_PROVIDER_UNSUPPORTED")
    if resolved_retrieval_settings.quality_repair_enabled and (
        resolved_retrieval_settings.semantic_hybrid_enabled
        or resolved_retrieval_settings.lexical_repair_enabled
        or resolved_retrieval_settings.rerank_enabled
        or resolved_retrieval_settings.metadata_repair_enabled
        or resolved_chat_settings.retrieval_planner_enabled
    ):
        raise RuntimeError("M08_QUALITY_RETRIEVAL_INCOMPATIBLE_OPTIONS")
    if resolved_retrieval_settings.semantic_hybrid_enabled and (
        resolved_retrieval_settings.lexical_repair_enabled
        or resolved_chat_settings.retrieval_planner_enabled
    ):
        raise RuntimeError("M08_SEMANTIC_HYBRID_INCOMPATIBLE_OPTIONS")
    if resolved_retrieval_settings.rerank_enabled and (
        not resolved_retrieval_settings.semantic_hybrid_enabled
        or resolved_retrieval_settings.lexical_repair_enabled
        or resolved_chat_settings.retrieval_planner_enabled
    ):
        raise RuntimeError("M08_RERANK_INCOMPATIBLE_OPTIONS")
    if resolved_retrieval_settings.metadata_repair_enabled and (
        not resolved_retrieval_settings.semantic_hybrid_enabled
        or not resolved_retrieval_settings.rerank_enabled
        or resolved_retrieval_settings.lexical_repair_enabled
        or resolved_chat_settings.retrieval_planner_enabled
    ):
        raise RuntimeError("M08_METADATA_REPAIR_INCOMPATIBLE_OPTIONS")

    provider: LLMProviderPort | None = None
    channel: ChannelPort | None = None
    recipients: OfficialBotRecipientRegistry | None = None
    try:
        provider = provider_factory(resolved_provider_settings)
        session_factory = session_factory_factory(engine)

        if resolved_retrieval_settings.quality_repair_enabled:
            quality_strategy = materialize_strategy(
                resolved_retrieval_settings.quality_strategy,
                resolved_retrieval_settings.quality_selected_pool,
            )
            if quality_strategy.family.reranker_enabled:
                raise RuntimeError("M08_QUALITY_RERANK_NOT_APPROVED")
            if not await semantic_coverage_checker(session_factory, active_source_ids):
                raise RuntimeError("M08_SEMANTIC_COVERAGE_INCOMPLETE")
            resolved_semantic_settings = (
                semantic_settings if semantic_settings is not None else SemanticSettings()
            )
            embedder = semantic_embedder_factory(resolved_semantic_settings)
            pipeline = LegalQualityCandidatePipeline(
                PostgresQualityCandidateReader(session_factory),
                embedder,
                quality_strategy,
                tuple(SourceId(source_id) for source_id in active_source_ids),
            )
            repository = PostgresQualityRetrievalRepository(
                session_factory, LegalQuestionAnalyzer(), pipeline
            )
            if quality_strategy.family.dynamic_evidence_enabled:
                resolved_chat_settings = resolved_chat_settings.model_copy(
                    update={"max_citations": 6}
                )
        elif resolved_retrieval_settings.semantic_hybrid_enabled:
            if not await semantic_coverage_checker(session_factory, active_source_ids):
                raise RuntimeError("M08_SEMANTIC_COVERAGE_INCOMPLETE")
            resolved_semantic_settings = (
                semantic_settings if semantic_settings is not None else SemanticSettings()
            )
            embedder = semantic_embedder_factory(resolved_semantic_settings)
            if resolved_retrieval_settings.rerank_enabled:
                resolved_reranker_settings = (
                    reranker_settings if reranker_settings is not None else RerankerSettings()
                )
                reranker = reranker_factory(resolved_reranker_settings)
                if resolved_retrieval_settings.metadata_repair_enabled:
                    repository = (
                        metadata_repair_repository_factory(
                            session_factory, active_source_ids, embedder, reranker
                        )
                        if metadata_repair_repository_factory is not None
                        else PostgresMetadataRepairRetrievalRepository(
                            session_factory,
                            active_source_ids,
                            embedder,
                            reranker,
                            timeout_seconds=getattr(
                                resolved_reranker_settings, "timeout_seconds", 5.0
                            ),
                        )
                    )
                else:
                    repository = (
                        reranked_repository_factory(
                            session_factory, active_source_ids, embedder, reranker
                        )
                        if reranked_repository_factory is not None
                        else PostgresRerankedSemanticRepository(
                            session_factory,
                            active_source_ids,
                            embedder,
                            reranker,
                            timeout_seconds=getattr(
                                resolved_reranker_settings, "timeout_seconds", 5.0
                            ),
                        )
                    )
            else:
                repository = (
                    hybrid_repository_factory(session_factory, active_source_ids, embedder)
                    if hybrid_repository_factory is not None
                    else PostgresHybridRetrievalRepository(
                        session_factory, active_source_ids, embedder, mode="hybrid"
                    )
                )
        else:
            repository = (
                lexical_repository_factory(session_factory, active_source_ids)
                if lexical_repository_factory is not None
                else PostgresLexicalRetrievalRepository(
                    session_factory,
                    active_source_ids,
                    lexical_repair_enabled=resolved_retrieval_settings.lexical_repair_enabled,
                )
            )
        retrieval = retrieval_service_factory(repository)
        grounding_evidence = grounding_evidence_factory(session_factory, resolved_chat_settings)
        resolver = citation_resolver_factory(session_factory)
        parser = parser_factory()
        query_planner: QueryPlannerPort | None = None
        canonical_anchor_resolver: CanonicalAnchorResolverPort | None = None
        if resolved_chat_settings.retrieval_planner_enabled:
            query_planner = query_planner_factory(
                provider, resolved_chat_settings, resolved_provider_settings
            )
            canonical_anchor_resolver = canonical_anchor_resolver_factory(
                session_factory, active_source_ids
            )
        grounded_chat = grounded_chat_service_factory(
            retrieval,
            grounding_evidence,
            resolver,
            provider,
            parser,
            resolved_chat_settings,
            resolved_provider_settings,
            query_planner,
            canonical_anchor_resolver,
        )

        conversation_repository = conversation_repository_factory(
            session_factory, resolved_conversation_settings
        )
        conversation = conversation_service_factory(
            conversation_repository,
            grounded_chat,
            resolver,
            resolved_conversation_settings,
        )
        binding_repository = binding_repository_factory(session_factory, channel_settings)
        outbound_repository = outbound_repository_factory(session_factory, channel_settings)
        formatter = formatter_factory(channel_settings)
        recipients = recipient_registry_factory()
        channel = channel_factory(channel_settings, recipients)
        ingress = channel_service_factory(
            binding_repository,
            outbound_repository,
            conversation,
            channel,
            formatter,
            channel_settings,
        )
        return ChannelRuntime(
            ingress=ingress,
            provider=provider,
            channel=channel,
            recipients=recipients,
        )
    except Exception:
        await _close_safely(channel)
        if recipients is not None:
            recipients.clear()
        await _close_safely(provider)
        raise RuntimeError("M08_RUNTIME_CONSTRUCTION_FAILED") from None


async def _close_safely(resource: ChannelPort | LLMProviderPort | None) -> None:
    """Best-effort construction rollback that never exposes adapter failure details."""

    if resource is None:
        return
    try:
        await resource.aclose()
    except Exception:
        pass
