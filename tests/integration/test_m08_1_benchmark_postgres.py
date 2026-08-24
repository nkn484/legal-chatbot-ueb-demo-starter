"""Opt-in deterministic PostgreSQL controlled benchmark for the M08.1 retrieval lane."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from legal_chatbot.chat.planner_models import (
    PLANNER_MAX_EXPANSION_TERMS,
    PLANNER_MAX_PHRASES,
)
from legal_chatbot.chat.planner_parser import StrictQueryPlannerParser
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
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository
from legal_chatbot.retrieval.benchmark_metrics import (
    BenchmarkMode,
    BenchmarkObservation,
    FallbackKind,
    compare_benchmark_modes,
)
from legal_chatbot.retrieval.models import RetrievalDecision, RetrievalRequest
from legal_chatbot.sources.models import ProvenanceType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_SOURCE_ID = "TESTM081"
_TOP_K = 2
_CASE_NATURAL = UUID(int=1)
_CASE_ORIGINAL = UUID(int=2)
_CASE_NO_MATCH = UUID(int=3)
_CASE_WRONG_SCOPE = UUID(int=4)


def _id(value: int) -> UUID:
    return UUID(int=value)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


async def _add_chunked_document(
    session: object,
    *,
    document_id: UUID,
    chunk_id: UUID,
    content: str,
    title: str | None = None,
    document_number: str | None = None,
) -> None:
    version_id = _id(1_000 + document_id.int)
    provenance_id = _id(2_000 + document_id.int)
    digest = _digest(f"{document_id}-{content}")
    session.add(  # type: ignore[attr-defined]
        LegalDocument(
            id=document_id,
            source_id=_SOURCE_ID,
            external_id=f"m08-benchmark-{document_id.int}",
        )
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
            snapshot_sha256=digest,
            source_content_sha256=digest,
            normalized_text_sha256=digest,
            normalizer_version="m08.1-benchmark",
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
            operation="m08_1_benchmark",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
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
            chunker_version="m08.1-benchmark",
            locator={"ordinal": 0},
        )
    )


@pytest.mark.asyncio
async def test_postgres_controlled_m08_1_benchmark_go_no_go_invariants() -> None:
    """Exercise raw and server-supplied planned requests against one fixed synthetic corpus."""

    engine = create_engine(Settings())
    session_factory = create_session_factory(engine)
    documents = {
        "natural": (_id(101), _id(201), "m08natural hoạt động khoa học nhiệm vụ nghiên cứu"),
        "original": (_id(102), _id(202), "m08original quyền lợi giảng viên"),
        "expanded": (_id(103), _id(203), "m08expanded nghĩa vụ nghiên cứu"),
        "scope": (_id(104), _id(204), "m08scope biện pháp khắc phục"),
        "outside": (_id(105), _id(205), "m08scope cảnh báo rộng"),
    }
    document_ids = tuple(document[0] for document in documents.values())
    run_ids: list[UUID] = []
    try:
        async with session_factory.begin() as session:
            for name, (document_id, chunk_id, content) in documents.items():
                await _add_chunked_document(
                    session,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    content=content,
                    title="Luật Giáo dục đại học" if name == "natural" else None,
                    document_number="34/2018/QH14" if name == "natural" else None,
                )

        repository = PostgresLexicalRetrievalRepository(session_factory, (_SOURCE_ID,))
        natural_question = (
            "Theo Luật Giáo dục đại học, m08natural tiêu chuẩn nghiên cứu khoa học như thế nào?"
        )
        parser = StrictQueryPlannerParser()
        valid_plan = parser.parse(
            dumps(
                {
                    "anchor_mentions": ["Luật Giáo dục đại học"],
                    "key_phrases": ["tiêu chuẩn nghiên cứu khoa học"],
                    "expansion_terms": ["m08natural hoạt động khoa học"],
                }
            ),
            natural_question,
            max_phrases=PLANNER_MAX_PHRASES,
            max_expansion_terms=PLANNER_MAX_EXPANSION_TERMS,
        )
        resolved_natural_document_ids = await PostgresCanonicalAnchorResolver(
            session_factory, (_SOURCE_ID,)
        ).resolve(valid_plan.anchor_mentions)
        assert resolved_natural_document_ids == (documents["natural"][0],)
        if resolved_natural_document_ids is None:
            raise AssertionError("valid canonical anchor did not resolve")

        protected_identity_probes = (
            "Luật Hư cấu 2099",
            "99/2099/QH99",
            "Điều 999 Khoản 9 Điểm z",
            "Bộ Hư cấu",
            "năm 2099",
            "hết hiệu lực",
        )
        accepted_probes: list[str] = []
        for probe in protected_identity_probes:
            unsafe_output = dumps(
                {
                    "anchor_mentions": ["Luật Giáo dục đại học"],
                    "key_phrases": ["tiêu chuẩn nghiên cứu khoa học"],
                    "expansion_terms": [probe],
                }
            )
            try:
                parser.parse(
                    unsafe_output,
                    natural_question,
                    max_phrases=PLANNER_MAX_PHRASES,
                    max_expansion_terms=PLANNER_MAX_EXPANSION_TERMS,
                )
            except ValueError:
                continue
            accepted_probes.append(probe)
        unsafe_plan_accepted = bool(accepted_probes)
        assert accepted_probes == []

        raw_requests = {
            _CASE_NATURAL: RetrievalRequest(query=natural_question, top_k=_TOP_K),
            _CASE_ORIGINAL: RetrievalRequest(query="m08original quyền lợi", top_k=_TOP_K),
            _CASE_NO_MATCH: RetrievalRequest(query="m08nomatch không tồn tại", top_k=_TOP_K),
            _CASE_WRONG_SCOPE: RetrievalRequest(query="m08scope cảnh báo rộng", top_k=_TOP_K),
        }
        planned_requests = {
            _CASE_NATURAL: RetrievalRequest(
                query=natural_question,
                expansion_query="m08natural hoạt động khoa học nhiệm vụ nghiên cứu",
                expansion_document_ids=resolved_natural_document_ids,
                top_k=_TOP_K,
            ),
            _CASE_ORIGINAL: RetrievalRequest(
                query="m08original quyền lợi",
                expansion_query="m08expanded nghĩa vụ nghiên cứu",
                expansion_document_ids=(documents["expanded"][0],),
                top_k=_TOP_K,
            ),
            _CASE_NO_MATCH: RetrievalRequest(
                query="m08nomatch không tồn tại",
                expansion_query="m08nomatch mở rộng không tồn tại",
                expansion_document_ids=(documents["natural"][0],),
                top_k=_TOP_K,
            ),
            _CASE_WRONG_SCOPE: RetrievalRequest(
                query="m08scope cảnh báo rộng",
                expansion_query="m08scope biện pháp khắc phục",
                expansion_document_ids=(documents["scope"][0],),
                top_k=_TOP_K,
            ),
        }
        raw_results = {}
        for case_id, request in raw_requests.items():
            result = await repository.retrieve_and_persist(request)
            raw_results[case_id] = result
            run_ids.append(result.retrieval_run_id)
        planned_results = {}
        for case_id, request in planned_requests.items():
            result = await repository.retrieve_and_persist(request)
            planned_results[case_id] = result
            run_ids.append(result.retrieval_run_id)

        natural_chunk = documents["natural"][1]
        original_chunk = documents["original"][1]
        expanded_chunk = documents["expanded"][1]
        scoped_chunk = documents["scope"][1]
        outside_chunk = documents["outside"][1]
        assert raw_results[_CASE_NATURAL].decision is RetrievalDecision.NO_RESULTS
        assert planned_results[_CASE_NATURAL].decision is RetrievalDecision.EVIDENCE_AVAILABLE
        assert planned_results[_CASE_NATURAL].candidates[0].document_chunk_id == natural_chunk
        assert (
            planned_results[_CASE_ORIGINAL].candidates[0].document_chunk_id
            == (raw_results[_CASE_ORIGINAL].candidates[0].document_chunk_id)
            == original_chunk
        )
        assert {
            candidate.document_chunk_id for candidate in planned_results[_CASE_ORIGINAL].candidates
        } == {
            original_chunk,
            expanded_chunk,
        }
        assert planned_results[_CASE_NO_MATCH].decision is RetrievalDecision.NO_RESULTS
        assert planned_results[_CASE_WRONG_SCOPE].candidates[0].document_chunk_id == outside_chunk
        assert scoped_chunk in {
            candidate.document_chunk_id
            for candidate in planned_results[_CASE_WRONG_SCOPE].candidates
        }

        gold_ids = {
            _CASE_NATURAL: frozenset((natural_chunk,)),
            _CASE_ORIGINAL: frozenset((original_chunk, expanded_chunk)),
            _CASE_NO_MATCH: frozenset(),
            _CASE_WRONG_SCOPE: frozenset((scoped_chunk,)),
        }

        def observation(
            case_id: UUID,
            mode: BenchmarkMode,
            result: object,
            *,
            end_to_end_latency_ms: float,
        ) -> BenchmarkObservation:
            ranked_ids = tuple(candidate.document_chunk_id for candidate in result.candidates)  # type: ignore[union-attr]
            return BenchmarkObservation(
                case_id=case_id,
                mode=mode,
                ranked_document_chunk_ids=ranked_ids,
                gold_document_chunk_ids=gold_ids[case_id],
                decision=result.decision,  # type: ignore[union-attr]
                wrong_scope=case_id is _CASE_WRONG_SCOPE and outside_chunk in ranked_ids,
                anchor_drift=(mode is BenchmarkMode.PLANNED and unsafe_plan_accepted),
                planner_latency_ms=None,
                end_to_end_latency_ms=end_to_end_latency_ms,
                fallback_kind=FallbackKind.NONE,
            )

        raw_observations = tuple(
            observation(case_id, BenchmarkMode.RAW, result, end_to_end_latency_ms=10.0)
            for case_id, result in raw_results.items()
        )
        planned_observations = tuple(
            observation(case_id, BenchmarkMode.PLANNED, result, end_to_end_latency_ms=12.0)
            for case_id, result in planned_results.items()
        )
        comparison = compare_benchmark_modes(raw_observations, planned_observations, k=_TOP_K)

        assert comparison.raw.hit_at_k == pytest.approx(1 / 3)
        assert comparison.raw.recall_at_k == pytest.approx(1 / 6)
        assert comparison.raw.mrr == pytest.approx(1 / 3)
        assert comparison.raw.no_results_rate == 0.5
        assert comparison.raw.wrong_scope_rate == 0.25
        assert comparison.planned.hit_at_k == 1.0
        assert comparison.planned.recall_at_k == 1.0
        assert comparison.planned.mrr == pytest.approx(5 / 6)
        assert comparison.planned.no_results_rate == 0.25
        assert comparison.planned.wrong_scope_rate == 0.25
        assert comparison.planned.hit_at_k >= comparison.raw.hit_at_k
        assert comparison.planned.recall_at_k >= comparison.raw.recall_at_k
        assert comparison.planned.mrr >= comparison.raw.mrr
        assert comparison.planned.no_results_rate < comparison.raw.no_results_rate
        assert comparison.planned.wrong_scope_rate <= comparison.raw.wrong_scope_rate
        assert comparison.planned.anchor_drift_rate == 0.0
        assert comparison.end_to_end_latency_delta_ms == 2.0

        async with session_factory() as session:
            for result in (*raw_results.values(), *planned_results.values()):
                run = await session.scalar(
                    select(RetrievalRun).where(RetrievalRun.id == result.retrieval_run_id)
                )
                citation_count = await session.scalar(
                    select(func.count())
                    .select_from(CitationRecord)
                    .where(CitationRecord.retrieval_run_id == result.retrieval_run_id)
                )
                assert run is not None
                assert run.strategy_version == (
                    "v2_planned" if result in planned_results.values() else "v1"
                )
                assert citation_count == result.citation_count == result.candidate_count
    finally:
        async with session_factory.begin() as session:
            if run_ids:
                await session.execute(
                    delete(CitationRecord).where(CitationRecord.retrieval_run_id.in_(run_ids))
                )
                await session.execute(delete(RetrievalRun).where(RetrievalRun.id.in_(run_ids)))
            await session.execute(delete(LegalDocument).where(LegalDocument.id.in_(document_ids)))
        await engine.dispose()
