"""Opt-in PostgreSQL checks for M08.1 canonical anchors and retrieval fusion."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.canonical_anchor_resolver import PostgresCanonicalAnchorResolver
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
)
from legal_chatbot.retrieval.models import RetrievalDecision, RetrievalRequest
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


async def _add_document(
    session: object,
    *,
    source_id: str,
    external_id: str,
    title: str | None,
    document_number: str | None,
    content: str,
    with_chunk: bool = False,
    tls_verified: bool = True,
) -> tuple[UUID, UUID | None]:
    document_id = uuid4()
    version_id = uuid4()
    document_digest = _digest(f"{document_id}-{content}")
    session.add(  # type: ignore[attr-defined]
        LegalDocument(id=document_id, source_id=source_id, external_id=external_id)
    )
    session.add(  # type: ignore[attr-defined]
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=1,
            title=title,
            document_number=document_number,
            raw_html=f"<p>{content}</p>",
            normalized_text=content,
            snapshot_sha256=document_digest,
            source_content_sha256=document_digest,
            normalized_text_sha256=document_digest,
            normalizer_version="m08.1-test",
            normalized_block_count=1,
        )
    )
    if not with_chunk:
        return document_id, None

    provenance_id = uuid4()
    chunk_id = uuid4()
    session.add(  # type: ignore[attr-defined]
        SourceProvenanceRecord(
            id=provenance_id,
            document_version_id=version_id,
            provenance_type=ProvenanceType.SOURCE_FETCH.value,
            source_id=source_id,
            transport="synthetic",
            operation="m08_1_test",
            retrieved_at=datetime.now(UTC),
            tls_verified=tls_verified,
        )
    )
    session.add(  # type: ignore[attr-defined]
        DocumentChunk(
            id=chunk_id,
            document_version_id=version_id,
            ordinal=0,
            content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(f"{chunk_id}-{content}"),
            chunker_version="m08.1-test",
            locator={"ordinal": 0},
        )
    )
    return document_id, chunk_id


async def _add_document_version(
    session: object,
    *,
    document_id: UUID,
    version_number: int,
    source_id: str,
    document_number: str,
    content: str,
) -> UUID:
    """Add a newer strict version fixture for latest-version retrieval checks."""

    version_id = uuid4()
    chunk_id = uuid4()
    digest = _digest(f"{version_id}-{content}")
    session.add(  # type: ignore[attr-defined]
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            version_number=version_number,
            document_number=document_number,
            raw_html=f"<p>{content}</p>",
            normalized_text=content,
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="m08.3-repair-test",
            normalized_block_count=1,
        )
    )
    session.add(  # type: ignore[attr-defined]
        SourceProvenanceRecord(
            id=uuid4(),
            document_version_id=version_id,
            provenance_type=ProvenanceType.SOURCE_FETCH.value,
            source_id=source_id,
            transport="synthetic",
            operation="m08_3_repair_test",
            retrieved_at=datetime.now(UTC),
            tls_verified=True,
        )
    )
    session.add(  # type: ignore[attr-defined]
        DocumentChunk(
            id=chunk_id,
            document_version_id=version_id,
            ordinal=0,
            content_text=content,
            start_char=0,
            end_char=len(content),
            content_sha256=_digest(f"{chunk_id}-{content}"),
            chunker_version="m08.3-repair-test",
            locator={"ordinal": 0},
        )
    )
    return chunk_id


@pytest.mark.asyncio
async def test_canonical_resolver_requires_exact_unique_latest_active_title_or_number() -> None:
    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_ids: list[UUID] = []
    try:
        async with session_factory.begin() as session:
            exact_id, _ = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-exact-{uuid4().hex}",
                title="Luật Giáo dục đại học",
                document_number="34/2018/QH14",
                content="canonical exact fixture",
            )
            document_ids.append(exact_id)
            for external_id, source_id in (
                (f"m08-ambiguous-a-{uuid4().hex}", "VBQPPL"),
                (f"m08-ambiguous-b-{uuid4().hex}", "VBQPPL"),
                (f"m08-inactive-{uuid4().hex}", "VNU"),
            ):
                document_id, _ = await _add_document(
                    session,
                    source_id=source_id,
                    external_id=external_id,
                    title="Ambiguous anchor" if source_id == "VBQPPL" else "Inactive anchor",
                    document_number=None,
                    content=external_id,
                )
                document_ids.append(document_id)

        resolver = PostgresCanonicalAnchorResolver(session_factory, ("VBQPPL",))
        assert await resolver.resolve((" luật  giáo DỤC đại học ",)) == (exact_id,)
        assert await resolver.resolve(("34/2018/qh14",)) == (exact_id,)
        assert await resolver.resolve(("Ambiguous anchor",)) is None
        assert await resolver.resolve(("Inactive anchor",)) is None
        assert await resolver.resolve(("Không tồn tại",)) is None
    finally:
        async with session_factory.begin() as session:
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_repair_generic_metadata_collision_is_unscoped_and_exact_number_is_scoped() -> None:
    """Metadata titles must not suppress matching content; exact IDs may scope it."""

    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_ids: list[UUID] = []
    run_ids: list[UUID] = []
    try:
        async with session_factory.begin() as session:
            collision_id, collision_chunk = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-repair-collision-{uuid4().hex}",
                title="Nghĩa vụ học phí target",
                document_number=None,
                content="metadata collision without matching evidence",
                with_chunk=True,
            )
            content_id, content_chunk = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-repair-content-{uuid4().hex}",
                title="Khác",
                document_number=None,
                content="nghĩa vụ học phí target applies",
                with_chunk=True,
            )
            exact_id, _ = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-repair-exact-{uuid4().hex}",
                title="Exact scope",
                document_number="2725/QĐ-ĐHKT",
                content="superseded lexical evidence",
                with_chunk=True,
            )
            exact_latest_chunk = await _add_document_version(
                session,
                document_id=exact_id,
                version_number=2,
                source_id="VBQPPL",
                document_number="2725/QĐ-ĐHKT",
                content="nghĩa vụ học phí target",
            )
            untrusted_id, untrusted_chunk = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-repair-untrusted-{uuid4().hex}",
                title="Untrusted duplicate",
                document_number="2725/QĐ-ĐHKT",
                content="nghĩa vụ học phí target",
                with_chunk=True,
                tls_verified=False,
            )
            unrelated_id, unrelated_chunk = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-repair-unrelated-{uuid4().hex}",
                title="Unrelated duplicate",
                document_number=None,
                content="nghĩa vụ học phí target",
                with_chunk=True,
            )
            document_ids.extend(
                (collision_id, content_id, exact_id, untrusted_id, unrelated_id)
            )

        repository = PostgresLexicalRetrievalRepository(
            session_factory, ("VBQPPL",), lexical_repair_enabled=True
        )
        generic = await repository.retrieve_and_persist(
            RetrievalRequest(query="cho tôi hỏi nghĩa vụ học phí target", top_k=10)
        )
        run_ids.append(generic.retrieval_run_id)
        generic_chunks = {candidate.document_chunk_id for candidate in generic.candidates}
        assert content_chunk in generic_chunks
        assert collision_chunk not in generic_chunks

        exact = await repository.retrieve_and_persist(
            RetrievalRequest(query="2725/QĐ-ĐHKT nghĩa vụ học phí target", top_k=10)
        )
        run_ids.append(exact.retrieval_run_id)
        assert tuple(candidate.document_chunk_id for candidate in exact.candidates) == (
            exact_latest_chunk,
        )
        exact_chunks = {candidate.document_chunk_id for candidate in exact.candidates}
        assert untrusted_chunk not in exact_chunks
        assert unrelated_chunk not in exact_chunks
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_planned_retrieval_uses_two_searches_and_persists_one_scoped_chain() -> None:
    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_ids: list[UUID] = []
    run_ids: list[UUID] = []
    try:
        async with session_factory.begin() as session:
            original_document_id, original_chunk_id = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-original-{uuid4().hex}",
                title="Original",
                document_number=None,
                content="m08origin token",
                with_chunk=True,
            )
            scoped_document_id, scoped_chunk_id = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-scoped-{uuid4().hex}",
                title="Scoped",
                document_number=None,
                content="m08expand token",
                with_chunk=True,
            )
            outside_document_id, outside_chunk_id = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-outside-{uuid4().hex}",
                title="Outside",
                document_number=None,
                content="m08expand token",
                with_chunk=True,
            )
            document_ids.extend((original_document_id, scoped_document_id, outside_document_id))

        class CountingRepository(PostgresLexicalRetrievalRepository):
            def __init__(self) -> None:
                super().__init__(session_factory, ("VBQPPL",))
                self.searches: list[tuple[str, int, tuple[UUID, ...] | None]] = []

            async def _select_candidates(
                self,
                session: AsyncSession,
                *,
                query: str,
                candidate_limit: int,
                document_ids: tuple[UUID, ...] | None = None,
                trust_scope=None,
            ) -> tuple[_CandidateRow, ...]:
                self.searches.append((query, candidate_limit, document_ids))
                return await super()._select_candidates(
                    session,
                    query=query,
                    candidate_limit=candidate_limit,
                    document_ids=document_ids,
                    trust_scope=trust_scope,
                )

        repository = CountingRepository()
        result = await repository.retrieve_and_persist(
            RetrievalRequest(
                query="m08origin",
                expansion_query="m08expand",
                expansion_document_ids=(scoped_document_id,),
                top_k=2,
            )
        )
        run_ids.append(result.retrieval_run_id)

        assert result.decision is RetrievalDecision.EVIDENCE_AVAILABLE
        assert tuple(candidate.document_chunk_id for candidate in result.candidates) == (
            original_chunk_id,
            scoped_chunk_id,
        )
        assert outside_chunk_id not in {
            candidate.document_chunk_id for candidate in result.candidates
        }
        assert repository.searches == [
            ("m08origin", 4, None),
            ("m08expand", 4, (scoped_document_id,)),
        ]
        async with session_factory() as session:
            run = await session.scalar(
                select(RetrievalRun).where(RetrievalRun.id == result.retrieval_run_id)
            )
            citations = await session.scalars(
                select(CitationRecord).where(
                    CitationRecord.retrieval_run_id == result.retrieval_run_id
                )
            )
            assert run is not None
            assert run.strategy_version == "v2_planned"
            assert len(tuple(citations)) == 2
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_expansion_failure_uses_original_evidence_without_a_second_persisted_run() -> None:
    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_ids: list[UUID] = []
    run_ids: list[UUID] = []
    try:
        async with session_factory.begin() as session:
            document_id, chunk_id = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-savepoint-{uuid4().hex}",
                title="Savepoint",
                document_number=None,
                content="m08savepoint original",
                with_chunk=True,
            )
            document_ids.append(document_id)

        class FailingExpansionRepository(PostgresLexicalRetrievalRepository):
            async def _retrieve_expansion_candidates(
                self, session: AsyncSession, request: RetrievalRequest
            ) -> tuple[_CandidateRow, ...]:
                del session, request
                raise RuntimeError("injected expansion SQL failure")

        failing_repository = FailingExpansionRepository(session_factory, ("VBQPPL",))
        result = await failing_repository.retrieve_and_persist(
            RetrievalRequest(
                query="m08savepoint",
                expansion_query="unused expansion",
                expansion_document_ids=(document_id,),
            )
        )
        run_ids.append(result.retrieval_run_id)
        assert result.decision is RetrievalDecision.EVIDENCE_AVAILABLE
        assert tuple(candidate.document_chunk_id for candidate in result.candidates) == (chunk_id,)
        async with session_factory() as session:
            persisted_runs = await session.scalar(
                select(func.count())
                .select_from(RetrievalRun)
                .where(RetrievalRun.id == result.retrieval_run_id)
            )
            persisted_citations = await session.scalar(
                select(func.count())
                .select_from(CitationRecord)
                .where(CitationRecord.retrieval_run_id == result.retrieval_run_id)
            )
            persisted_run = await session.scalar(
                select(RetrievalRun).where(RetrievalRun.id == result.retrieval_run_id)
            )
            assert persisted_runs == 1
            assert persisted_citations == 1
            assert persisted_run is not None
            assert persisted_run.strategy_version == "v1"
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()


@pytest.mark.asyncio
async def test_source_isolation_filters_original_and_expansion_to_explicit_active_sources() -> None:
    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    document_ids: list[UUID] = []
    run_ids: list[UUID] = []
    try:
        async with session_factory.begin() as session:
            official_original_id, official_original_chunk = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-isolation-official-original-{uuid4().hex}",
                title="Official original",
                document_number=None,
                content="m08isolation original",
                with_chunk=True,
            )
            official_expansion_id, official_expansion_chunk = await _add_document(
                session,
                source_id="VBQPPL",
                external_id=f"m08-isolation-official-expansion-{uuid4().hex}",
                title="Official expansion",
                document_number=None,
                content="m08isolation expansion",
                with_chunk=True,
            )
            fixture_original_id, fixture_original_chunk = await _add_document(
                session,
                source_id="TESTM05",
                external_id=f"m08-isolation-fixture-original-{uuid4().hex}",
                title="Fixture original",
                document_number=None,
                content="m08isolation original",
                with_chunk=True,
            )
            fixture_expansion_id, fixture_expansion_chunk = await _add_document(
                session,
                source_id="TESTM05",
                external_id=f"m08-isolation-fixture-expansion-{uuid4().hex}",
                title="Fixture expansion",
                document_number=None,
                content="m08isolation expansion",
                with_chunk=True,
            )
            document_ids.extend(
                (
                    official_original_id,
                    official_expansion_id,
                    fixture_original_id,
                    fixture_expansion_id,
                )
            )

        official_repository = PostgresLexicalRetrievalRepository(session_factory, ("VBQPPL",))
        official_result = await official_repository.retrieve_and_persist(
            RetrievalRequest(
                query="m08isolation original",
                expansion_query="m08isolation expansion",
                expansion_document_ids=(official_expansion_id, fixture_expansion_id),
                top_k=2,
            )
        )
        run_ids.append(official_result.retrieval_run_id)
        assert tuple(candidate.document_chunk_id for candidate in official_result.candidates) == (
            official_original_chunk,
            official_expansion_chunk,
        )
        assert fixture_original_chunk not in {
            candidate.document_chunk_id for candidate in official_result.candidates
        }
        assert fixture_expansion_chunk not in {
            candidate.document_chunk_id for candidate in official_result.candidates
        }

        fixture_repository = PostgresLexicalRetrievalRepository(session_factory, ("TESTM05",))
        fixture_result = await fixture_repository.retrieve_and_persist(
            RetrievalRequest(
                query="m08isolation original",
                expansion_query="m08isolation expansion",
                expansion_document_ids=(fixture_expansion_id,),
                top_k=2,
            )
        )
        run_ids.append(fixture_result.retrieval_run_id)
        assert tuple(candidate.document_chunk_id for candidate in fixture_result.candidates) == (
            fixture_original_chunk,
            fixture_expansion_chunk,
        )
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            if document_ids:
                await session.execute(
                    delete(LegalDocument).where(LegalDocument.id.in_(document_ids))
                )
        await engine.dispose()
