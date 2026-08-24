"""Opt-in PostgreSQL vertical coverage for the M06 grounded-chat flow."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text

from legal_chatbot.chat import (
    ChatOutcome,
    ChatReasonCode,
    ChatRequest,
    ChatSettings,
    GroundedChatService,
)
from legal_chatbot.chat.parser import StrictProviderJsonParser
from legal_chatbot.core.config import Settings
from legal_chatbot.core.logging import JsonFormatter
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.grounding_evidence import PostgresGroundingEvidenceAdapter
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    GenerationResult,
    ProviderErrorCode,
    ProviderHealth,
    ProviderHealthStatus,
)
from legal_chatbot.retrieval.models import (
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    TemporalScope,
)
from legal_chatbot.retrieval.service import RetrievalService
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_SOURCE_ID = "TESTM06CHAT"
_QUESTION_SENTINEL = "QUESTION_LOG_SENTINEL"
_EXCERPT_SENTINEL = "EXCERPT_LOG_SENTINEL"
_PROVIDER_EXCEPTION_SENTINEL = "PROVIDER_EXCEPTION_SENTINEL"


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


async def _add_version(
    session: object,
    *,
    document_id: UUID,
    version_number: int,
    chunks: tuple[str, ...],
    retrieved_at: datetime,
) -> tuple[UUID, UUID, tuple[UUID, ...]]:
    """Seed only this test's document version, provenance, and bounded chunks."""

    version_id = uuid4()
    provenance_id = uuid4()
    normalized_text = "\n".join(chunks)
    digest = _digest(f"{document_id}-{version_number}-{normalized_text}")
    session.add(  # type: ignore[attr-defined]
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            raw_html=f"<p>{normalized_text}</p>",
            normalized_text=normalized_text,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="m06-chat-postgres-test",
            normalized_block_count=1,
        )
    )
    session.add(  # type: ignore[attr-defined]
        SourceProvenanceRecord(
            id=provenance_id,
            document_version_id=version_id,
            provenance_type=ProvenanceType.SOURCE_FETCH.value,
            source_id=_SOURCE_ID,
            transport="synthetic",
            operation="m06_grounded_chat_postgres_test",
            retrieved_at=retrieved_at,
            tls_verified=True,
        )
    )
    chunk_ids: list[UUID] = []
    offset = 0
    for ordinal, chunk_text in enumerate(chunks):
        chunk_id = uuid4()
        chunk_ids.append(chunk_id)
        session.add(  # type: ignore[attr-defined]
            DocumentChunk(
                id=chunk_id,
                document_version_id=version_id,
                ordinal=ordinal,
                content_text=chunk_text,
                start_char=offset,
                end_char=offset + len(chunk_text),
                content_sha256=_digest(chunk_text),
                chunker_version="m06-chat-postgres-test",
                locator={"ordinal": ordinal},
            )
        )
        offset += len(chunk_text) + 1
    return version_id, provenance_id, tuple(chunk_ids)


async def _counts(session_factory: object) -> tuple[int, int, int]:
    async with session_factory() as session:  # type: ignore[operator]
        runs = await session.scalar(select(func.count()).select_from(RetrievalRun))
        citations = await session.scalar(select(func.count()).select_from(CitationRecord))
        documents = await session.scalar(select(func.count()).select_from(LegalDocument))
    return int(runs or 0), int(citations or 0), int(documents or 0)


class _TrackingRetrievalPort:
    """Retain only in-memory requests/results from the real retrieval service for assertions."""

    def __init__(self, service: RetrievalService) -> None:
        self._service = service
        self.requests: list[RetrievalRequest] = []
        self.results: list[RetrievalResult] = []

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self.requests.append(request)
        result = await self._service.retrieve(request)
        self.results.append(result)
        return result


class _BoundedFakeProvider:
    """Provider fake that cannot send network traffic and records exactly one request per call."""

    def __init__(self, result: GenerationResult | Exception) -> None:
        self._result = result
        self.calls: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderHealthStatus.HEALTHY,
            provider="m06-fake",
            model="m06-fake-model",
            duration_ms=0,
        )

    async def aclose(self) -> None:
        return None


def _provider_settings() -> ProviderSettings:
    return ProviderSettings.model_validate(
        {
            "LLM_BASE_URL": "https://provider.example.test/v1",
            "LLM_MODEL": "m06-fake-model",
            "LLM_API_KEY": "m06-test-key",
            "LLM_MAX_INPUT_CHARS": 20_000,
            "LLM_MAX_OUTPUT_TOKENS": 512,
        }
    )


def _provider_result() -> GenerationResult:
    return GenerationResult(
        text='{"answer":"Grounded response prose only."}',
        provider="m06-fake",
        model="m06-fake-model",
        request_id="m06-request-1",
        duration_ms=0,
    )


@pytest.mark.asyncio
async def test_m06_grounded_chat_postgres_vertical_slice(caplog: pytest.LogCaptureFixture) -> None:
    """Exercise real retrieval, evidence, and resolution with fake providers only."""

    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_id = uuid4()
    run_ids: list[UUID] = []
    token = f"m06chathit{uuid4().hex}"
    known_question = f"{token} {_QUESTION_SENTINEL}"
    no_hit_question = f"m06chatnohit{uuid4().hex}"
    now = datetime.now(UTC)
    current_version_id: UUID | None = None
    current_provenance_id: UUID | None = None
    current_chunk_ids: tuple[UUID, ...] = ()
    direct_run_id = uuid4()
    direct_citation_id = uuid4()

    try:
        async with session_factory.begin() as session:
            session.add(
                LegalDocument(
                    id=document_id,
                    source_id=_SOURCE_ID,
                    external_id=f"testm06chat-{document_id.hex}",
                )
            )
            _, prior_provenance_id, _ = await _add_version(
                session,
                document_id=document_id,
                version_number=1,
                chunks=("m06chat historical cross-version evidence",),
                retrieved_at=now - timedelta(days=1),
            )
            current_version_id, current_provenance_id, current_chunk_ids = await _add_version(
                session,
                document_id=document_id,
                version_number=2,
                chunks=(
                    f"{token} {_QUESTION_SENTINEL} {_EXCERPT_SENTINEL} first evidence",
                    f"{token} {_QUESTION_SENTINEL} {_EXCERPT_SENTINEL} second evidence",
                ),
                retrieved_at=now,
            )
            session.add_all(
                (
                    RetrievalRun(
                        id=direct_run_id,
                        strategy="postgresql_fts",
                        strategy_version="v1",
                        scope="LATEST_INGESTED",
                        query_max_chars=4_000,
                        top_k=1,
                        candidate_count=1,
                        citation_count=1,
                        evidence_decision=RetrievalDecision.EVIDENCE_AVAILABLE.value,
                        evidence_reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE.value,
                    ),
                    CitationRecord(
                        id=direct_citation_id,
                        retrieval_run_id=direct_run_id,
                        document_chunk_id=current_chunk_ids[0],
                        source_provenance_record_id=prior_provenance_id,
                        rank=1,
                        lexical_score=1,
                    ),
                )
            )
        run_ids.append(direct_run_id)
        before_runs, before_citations, before_documents = await _counts(session_factory)

        repository = PostgresLexicalRetrievalRepository(session_factory, (_SOURCE_ID,))
        retrieval = _TrackingRetrievalPort(RetrievalService(repository))
        grounding = PostgresGroundingEvidenceAdapter(
            session_factory,
            ChatSettings(max_citations=2, total_evidence_max_chars=4_000),
        )
        resolver = PostgresCitationResolver(session_factory)
        chat_settings = ChatSettings(max_citations=2, total_evidence_max_chars=4_000)
        provider_settings = _provider_settings()

        def service_for(
            provider: _BoundedFakeProvider, retrieval_port: object = retrieval
        ) -> GroundedChatService:
            return GroundedChatService(
                retrieval_port,  # type: ignore[arg-type]
                grounding,
                resolver,
                provider,
                StrictProviderJsonParser(),
                chat_settings,
                provider_settings,
            )

        caplog.set_level(logging.INFO, logger="legal_chatbot")
        hit_provider = _BoundedFakeProvider(_provider_result())
        hit = await service_for(hit_provider).respond(ChatRequest(question=known_question))
        hit_run = retrieval.results[-1]
        run_ids.append(hit_run.retrieval_run_id)

        assert hit.outcome is ChatOutcome.ANSWER
        assert hit.reason is ChatReasonCode.ANSWER_GROUNDED
        assert len(hit_provider.calls) == 1
        assert hit.answer == "Grounded response prose only."
        assert all(
            marker not in hit_provider._result.text.casefold()  # type: ignore[union-attr]
            for marker in ("citation", "uuid", "source", "document")
        )
        assert tuple(citation.citation_id for citation in hit.citations) == tuple(
            candidate.citation_id for candidate in hit_run.candidates
        )
        assert tuple(citation.document_chunk_id for citation in hit.citations) == tuple(
            candidate.document_chunk_id for candidate in hit_run.candidates
        )
        assert all(
            citation.retrieval_run_id == hit_run.retrieval_run_id for citation in hit.citations
        )
        assert all(citation.document_id == document_id for citation in hit.citations)
        assert all(citation.document_version_id == current_version_id for citation in hit.citations)
        assert all(
            citation.source_provenance_record_id == current_provenance_id
            for citation in hit.citations
        )
        assert all(citation.source_id == _SOURCE_ID for citation in hit.citations)

        async with session_factory() as session:
            persisted_hit_citations = tuple(
                await session.scalars(
                    select(CitationRecord.id)
                    .where(CitationRecord.retrieval_run_id == hit_run.retrieval_run_id)
                    .order_by(CitationRecord.rank)
                )
            )
        assert persisted_hit_citations == tuple(
            candidate.citation_id for candidate in hit_run.candidates
        )

        no_hit_provider = _BoundedFakeProvider(_provider_result())
        no_hit = await service_for(no_hit_provider).respond(ChatRequest(question=no_hit_question))
        no_hit_run = retrieval.results[-1]
        run_ids.append(no_hit_run.retrieval_run_id)
        assert no_hit.outcome is ChatOutcome.CLARIFICATION
        assert no_hit.reason is ChatReasonCode.NO_RESULTS
        assert no_hit_provider.calls == []
        assert no_hit_run.decision is RetrievalDecision.NO_RESULTS
        assert no_hit_run.candidates == ()

        temporal_runs: list[UUID] = []
        for temporal_request in (
            ChatRequest(question=token, temporal_scope=TemporalScope.AS_OF),
            ChatRequest(question=f"{token} currently effective"),
        ):
            temporal_provider = _BoundedFakeProvider(_provider_result())
            temporal = await service_for(temporal_provider).respond(temporal_request)
            temporal_run = retrieval.results[-1]
            run_ids.append(temporal_run.retrieval_run_id)
            temporal_runs.append(temporal_run.retrieval_run_id)
            assert temporal.outcome is ChatOutcome.REFUSAL
            assert temporal.reason is ChatReasonCode.UNSUPPORTED_TEMPORAL_SCOPE
            assert temporal_provider.calls == []
            assert temporal_run.decision is RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE
            assert temporal_run.candidates == ()
        assert [request.temporal_scope for request in retrieval.requests[-2:]] == [
            TemporalScope.AS_OF,
            TemporalScope.CURRENT_EFFECT,
        ]

        class _CrossVersionRetrievalPort:
            async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
                del request
                return RetrievalResult(
                    retrieval_run_id=direct_run_id,
                    candidates=(
                        RetrievalCandidate(
                            citation_id=direct_citation_id,
                            document_chunk_id=current_chunk_ids[0],
                            rank=1,
                            lexical_score=1,
                        ),
                    ),
                    candidate_count=1,
                    citation_count=1,
                    decision=RetrievalDecision.EVIDENCE_AVAILABLE,
                    reason=RetrievalReason.LEXICAL_EVIDENCE_AVAILABLE,
                )

        invalid_provider = _BoundedFakeProvider(_provider_result())
        invalid = await service_for(invalid_provider, _CrossVersionRetrievalPort()).respond(
            ChatRequest(question=token)
        )
        assert invalid.outcome is ChatOutcome.REFUSAL
        assert invalid.reason is ChatReasonCode.GROUNDING_FAILURE
        assert invalid_provider.calls == []

        timeout_provider = _BoundedFakeProvider(ProviderError(ProviderErrorCode.TIMEOUT))
        timeout = await service_for(timeout_provider).respond(ChatRequest(question=known_question))
        timeout_run = retrieval.results[-1]
        run_ids.append(timeout_run.retrieval_run_id)
        assert timeout.outcome is ChatOutcome.REFUSAL
        assert timeout.reason is ChatReasonCode.PROVIDER_FAILURE
        assert len(timeout_provider.calls) == 1
        assert timeout.citations == ()

        exception_provider = _BoundedFakeProvider(RuntimeError(_PROVIDER_EXCEPTION_SENTINEL))
        exception_result = await service_for(exception_provider).respond(
            ChatRequest(question=known_question)
        )
        exception_run = retrieval.results[-1]
        run_ids.append(exception_run.retrieval_run_id)
        assert exception_result.reason is ChatReasonCode.PROVIDER_FAILURE
        assert len(exception_provider.calls) == 1
        assert exception_result.citations == ()

        async with session_factory() as session:
            temporal_rows = tuple(
                await session.scalars(
                    select(RetrievalRun).where(RetrievalRun.id.in_(temporal_runs))
                )
            )
            assert len(temporal_rows) == 2
            assert all(row.candidate_count == row.citation_count == 0 for row in temporal_rows)
            assert all(
                row.evidence_decision == RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE.value
                for row in temporal_rows
            )
            no_hit_row = await session.get(RetrievalRun, no_hit_run.retrieval_run_id)
            assert no_hit_row is not None
            assert no_hit_row.candidate_count == no_hit_row.citation_count == 0
            assert no_hit_row.evidence_decision == RetrievalDecision.NO_RESULTS.value

            table_names = set(
                await session.scalars(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema()"
                    )
                )
            )
            assert not any("chat" in table_name.casefold() for table_name in table_names)
            columns = set(
                await session.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name IN ('retrieval_runs', 'citation_records')"
                    )
                )
            )
        forbidden_columns = {
            "question",
            "question_hash",
            "prompt",
            "excerpt",
            "excerpt_text",
            "model_response",
            "provider_body",
        }
        assert not {column_name for _, column_name in columns} & forbidden_columns

        after_runs, after_citations, after_documents = await _counts(session_factory)
        assert (after_runs, after_citations, after_documents) == (
            before_runs + 6,
            before_citations + 6,
            before_documents,
        )

        formatter = JsonFormatter()
        serialized_logs = "\n".join(
            f"{record.__dict__}\n{formatter.format(record)}" for record in caplog.records
        )
        assert all(
            sentinel not in serialized_logs
            for sentinel in (
                _QUESTION_SENTINEL,
                _EXCERPT_SENTINEL,
                _PROVIDER_EXCEPTION_SENTINEL,
            )
        )
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            await session.execute(delete(LegalDocument).where(LegalDocument.id == document_id))
        await engine.dispose()
