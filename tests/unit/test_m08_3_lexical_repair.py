"""Focused lexical-repair safety and three-lane retrieval behavior."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from legal_chatbot.documents.orm import CitationRecord, RetrievalRun
from legal_chatbot.documents.retrieval_repository import (
    PostgresLexicalRetrievalRepository,
    _CandidateRow,
    _extract_document_numbers,
    compile_lexical_repair_query,
)
from legal_chatbot.retrieval.models import RetrievalRequest, RetrievalTrustScope


def _row(value: int) -> _CandidateRow:
    version_id = UUID(int=100 + value)
    return _CandidateRow(UUID(int=value), version_id, UUID(int=200 + value), version_id, 1.0)


@pytest.mark.parametrize(
    "question",
    (
        "nghĩa vụ\x00 học phí",
        "https://example.test nghĩa vụ học phí",
        "nghĩa vụ & học phí",
        "nghĩa",  # A phrase must contain at least two terms.
    ),
)
def test_repair_compiler_fails_closed_for_unsafe_or_singleton_questions(question: str) -> None:
    assert compile_lexical_repair_query(question) is None


def test_repair_compiler_normalizes_nfc_and_bounds_two_user_derived_phrases() -> None:
    question = "cho tôi hỏi điều kiện tuyển sinh một hai ba và học phí chương trình sau đại học"

    repair = compile_lexical_repair_query(question)

    assert repair == '"điều kiện tuyển sinh một" OR "học phí chương trình sau"'
    assert repair.count(" OR ") == 1
    assert all(2 <= len(phrase.split()) <= 5 for phrase in repair.replace('"', "").split(" OR "))
    assert "điều" not in repair
    assert compile_lexical_repair_query("34/2018/QH14") is None
    assert _extract_document_numbers(
        "Theo 34/2018/qh14, 2725/QĐ-ĐHKT, 5858/QĐ-ĐHQGHN"
    ) == (
        "34/2018/qh14",
        "2725/qđ-đhkt",
    )
    assert _extract_document_numbers("5858/QĐ-ĐHQGHN") == ("5858/qđ-đhqghn",)
    assert _extract_document_numbers("Họp ngày 12/05/2024 và 01/01/2025") == ()


def test_repair_compiler_splits_clauses_and_displaces_low_signal_phrases() -> None:
    assert compile_lexical_repair_query("quy định; học phí chương trình sau đại học") == (
        '"học phí chương trình sau"'
    )
    assert compile_lexical_repair_query("nghĩa vụ, điều kiện tuyển sinh học phí") == (
        '"điều kiện tuyển sinh học" OR "nghĩa vụ"'
    )
    assert compile_lexical_repair_query("nghĩa vụ - học phí") == '"nghĩa vụ" OR "học phí"'


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def begin(self) -> _Session:
        return self

    def begin_nested(self) -> _Session:
        return self

    async def execute(self, *_: object, **__: object) -> object:
        return object()

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None


class _Factory:
    def __init__(self, session: _Session) -> None:
        self._session = session

    def __call__(self) -> _Session:
        return self._session


class _LaneRepository(PostgresLexicalRetrievalRepository):
    def __init__(
        self,
        session: _Session,
        *,
        raw: tuple[_CandidateRow, ...] = (),
        repair: tuple[_CandidateRow, ...] = (),
        expansion: tuple[_CandidateRow, ...] = (),
    ) -> None:
        super().__init__(
            _Factory(session), ("VBQPPL",), lexical_repair_enabled=True
        )  # type: ignore[arg-type]
        self.raw = raw
        self.repair = repair
        self.expansion = expansion
        self.calls: list[tuple[str, str, tuple[UUID, ...] | None, RetrievalTrustScope]] = []
        self.metadata_document_id = uuid4()

    async def _retrieve_candidates(
        self, session: object, request: RetrievalRequest
    ) -> tuple[_CandidateRow, ...]:
        del session
        self.calls.append(("raw", request.query, None, request.trust_scope))
        return self.raw

    async def _identify_metadata_document_ids(
        self, session: object, **kwargs: object
    ) -> tuple[UUID, ...]:
        del session
        question = kwargs["question"]
        if isinstance(question, str) and _extract_document_numbers(question):
            return (self.metadata_document_id,)
        return ()

    async def _retrieve_repair_candidates(
        self,
        session: object,
        request: RetrievalRequest,
        repair_query: str | None,
        metadata_document_ids: tuple[UUID, ...],
    ) -> tuple[_CandidateRow, ...]:
        del session
        if repair_query is not None:
            self.calls.append(("repair", repair_query, metadata_document_ids, request.trust_scope))
        return self.repair if repair_query is not None else ()

    async def _retrieve_expansion_candidates(
        self, session: object, request: RetrievalRequest
    ) -> tuple[_CandidateRow, ...]:
        del session
        self.calls.append(("expansion", request.expansion_query or "", None, request.trust_scope))
        return self.expansion


@pytest.mark.asyncio
async def test_generic_repair_can_supply_only_evidence_without_metadata_scope() -> None:
    evidence_session = _Session()
    repository = _LaneRepository(evidence_session, repair=(_row(2),))
    request = RetrievalRequest(query="cho tôi hỏi nghĩa vụ học phí")

    result = await repository.retrieve_and_persist(request)

    assert tuple(candidate.document_chunk_id for candidate in result.candidates) == (
        _row(2).document_chunk_id,
    )
    assert repository.calls == [
        ("raw", request.query, None, RetrievalTrustScope.STRICT_TLS_ONLY),
        (
            "repair",
            '"nghĩa vụ học phí"',
            (),
            RetrievalTrustScope.STRICT_TLS_ONLY,
        ),
    ]
    assert len([item for item in evidence_session.added if isinstance(item, RetrievalRun)]) == 1
    assert len([item for item in evidence_session.added if isinstance(item, CitationRecord)]) == 1

    assert await PostgresLexicalRetrievalRepository._identify_metadata_document_ids(
        repository,
        None,  # type: ignore[arg-type]
        question=request.query,
        repair_query='"nghĩa vụ học phí"',
        trust_scope=request.trust_scope,
    ) == ()


@pytest.mark.asyncio
async def test_exact_document_number_scopes_repair_but_content_still_must_match() -> None:
    session = _Session()
    repository = _LaneRepository(session, repair=(_row(2),))
    request = RetrievalRequest(query="2725/QĐ-ĐHKT nghĩa vụ học phí")

    result = await repository.retrieve_and_persist(request)

    assert len(result.candidates) == 1
    assert repository.calls[1] == (
        "repair",
        '"nghĩa vụ học phí"',
        (repository.metadata_document_id,),
        RetrievalTrustScope.STRICT_TLS_ONLY,
    )
    assert len([item for item in session.added if isinstance(item, CitationRecord)]) == 1


@pytest.mark.asyncio
async def test_disabled_repair_uses_raw_only_and_persists_v1() -> None:
    session = _Session()
    repository = _LaneRepository(session, raw=(_row(1),), repair=(_row(2),))
    repository._lexical_repair_enabled = False

    await repository.retrieve_and_persist(RetrievalRequest(query="nghĩa vụ học phí"))

    assert [call[0] for call in repository.calls] == ["raw"]
    run = next(item for item in session.added if isinstance(item, RetrievalRun))
    assert run.strategy_version == "v1"


@pytest.mark.asyncio
async def test_planned_retrieval_uses_at_most_raw_repair_and_expansion_lanes() -> None:
    session = _Session()
    repository = _LaneRepository(session, raw=(_row(1),), repair=(_row(2),), expansion=(_row(3),))
    request = RetrievalRequest(
        query="cho tôi hỏi nghĩa vụ học phí",
        expansion_query="mở rộng hợp lệ",
        expansion_document_ids=(uuid4(),),
        trust_scope=RetrievalTrustScope.ALLOW_USER_APPROVED_TOFU_PINNED_EXCEPTION,
        top_k=3,
    )

    result = await repository.retrieve_and_persist(request)

    assert {call[0] for call in repository.calls} == {"raw", "repair", "expansion"}
    assert len(repository.calls) == 3
    assert all(call[3] is request.trust_scope for call in repository.calls)
    assert len(result.candidates) == 3
