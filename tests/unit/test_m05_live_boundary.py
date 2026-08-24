"""Static and narrow boundary checks for the M05 live adapters."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
)
from legal_chatbot.retrieval.models import (
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
)


class _Session:
    def __init__(self) -> None:
        self.executed = 0
        self.added: list[object] = []

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> _Session:
        return self

    async def execute(self, *args: object, **kwargs: object) -> object:
        self.executed += 1
        return object()

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None


class _Factory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __call__(self) -> _Session:
        return self.session


@pytest.mark.asyncio
async def test_temporal_zero_evidence_does_not_execute_search() -> None:
    session = _Session()
    repository = PostgresLexicalRetrievalRepository(  # type: ignore[arg-type]
        _Factory(session), ("TESTM05",)
    )

    result = await repository.persist_zero_evidence_run(
        RetrievalRequest(query="temporal test"),
        RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
        RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED,
    )

    assert session.executed == 0
    assert result.decision is RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE
    assert result.candidates == ()


@pytest.mark.asyncio
async def test_invalid_candidate_chain_is_persisted_as_zero_evidence() -> None:
    session = _Session()

    class _MismatchedRepository(PostgresLexicalRetrievalRepository):
        async def _retrieve_candidates(
            self, session: AsyncSession, request: RetrievalRequest
        ) -> tuple[_CandidateRow, ...]:
            del session, request
            return (
                _CandidateRow(
                    document_chunk_id=uuid4(),
                    document_version_id=uuid4(),
                    source_provenance_record_id=uuid4(),
                    source_provenance_document_version_id=uuid4(),
                    lexical_score=1.0,
                ),
            )

        async def _identify_metadata_document_ids(
            self, session: AsyncSession, **_: object
        ) -> tuple:
            del session
            return ()

        async def _retrieve_repair_candidates(
            self,
            session: AsyncSession,
            request: RetrievalRequest,
            repair_query: str | None,
            metadata_document_ids: tuple,
        ) -> tuple:
            del session, request, repair_query, metadata_document_ids
            return ()

    repository = _MismatchedRepository(_Factory(session), ("TESTM05",))  # type: ignore[arg-type]
    result = await repository.retrieve_and_persist(RetrievalRequest(query="chain test"))

    assert result.decision is RetrievalDecision.INVALID_EVIDENCE_CHAIN
    assert result.reason is RetrievalReason.INVALID_EVIDENCE_CHAIN
    assert result.candidates == ()
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_captured_production_log_omits_query_sentinel(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _Session()
    repository = PostgresLexicalRetrievalRepository(  # type: ignore[arg-type]
        _Factory(session), ("TESTM05",)
    )
    sentinel = "RAW_QUERY_SENTINEL"
    caplog.set_level(logging.INFO, logger="legal_chatbot")

    await repository.persist_zero_evidence_run(
        RetrievalRequest(query=sentinel),
        RetrievalDecision.UNSUPPORTED_TEMPORAL_SCOPE,
        RetrievalReason.TEMPORAL_SCOPE_UNSUPPORTED,
    )

    logged = json.dumps([record.__dict__ for record in caplog.records], default=str)
    assert sentinel not in logged
    assert [record.message for record in caplog.records] == ["retrieval_complete"]


def test_live_adapter_sources_exclude_disallowed_dependencies_and_persistence() -> None:
    root = Path(__file__).parents[2]
    live_sources = "\n".join(
        (root / "src/legal_chatbot/documents" / filename).read_text(encoding="utf-8").lower()
        for filename in ("retrieval_repository.py", "citation_resolver.py")
    )

    forbidden = (
        "pgvector",
        "chunkembedding",
        "chunk_embeddings",
        "embedding",
        "<=>",
        "<->",
        "reciprocal_rank",
        "legal_chatbot.providers",
        "legal_chatbot.chat",
        "legal_chatbot.channel",
        "legal_chatbot.api",
        "query_hash",
        "content_text",
        "raw_query",
    )
    assert not {token for token in forbidden if token in live_sources}
    # Metadata is exact-number-only, so content retrieval retains its one bounded parser.
    assert live_sources.count("websearch_to_tsquery") == 1
    assert "'pg_catalog.simple'::regconfig" in live_sources
