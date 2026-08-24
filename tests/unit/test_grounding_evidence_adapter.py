"""Unit checks for the read-only grounding evidence adapter."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from legal_chatbot.chat import ChatError, ChatErrorCode, GroundingEvidenceRequest
from legal_chatbot.documents.grounding_evidence import (
    PostgresGroundingEvidenceAdapter,
    _GroundingRow,
)


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[tuple[object, ...], ...]:
        return self._rows


class _Session:
    def __init__(self, result: _Result | Exception) -> None:
        self.result = result
        self.statement_count = 0

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: object) -> _Result:
        del statement
        self.statement_count += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _settings(**overrides: int) -> SimpleNamespace:
    return SimpleNamespace(
        max_citations=overrides.get("max_citations", 3),
        excerpt_max_chars=overrides.get("excerpt_max_chars", 20),
        total_evidence_max_chars=overrides.get("total_evidence_max_chars", 20),
    )


def _row(
    *,
    citation_id: UUID | None = None,
    run_id: UUID | None = None,
    provenance_id: UUID | None = None,
    version_id: UUID | None = None,
    document_version_id: UUID | None = None,
    text: str = "evidence text",
) -> _GroundingRow:
    document_version_id = document_version_id or version_id or uuid4()
    return _GroundingRow(
        citation_id=citation_id or uuid4(),
        retrieval_run_id=run_id or uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=document_version_id,
        version_id=version_id or document_version_id,
        document_id=uuid4(),
        source_provenance_record_id=provenance_id or uuid4(),
        source_id="TESTM06",
        external_id="m06-test",
        document_number="01/2026",
        title="Test evidence",
        canonical_url="https://example.test/m06",
        locator={"section": 1},
        content_text=text,
    )


def _as_result_rows(rows: tuple[_GroundingRow, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            row.citation_id,
            row.retrieval_run_id,
            row.document_chunk_id,
            row.document_version_id,
            row.version_id,
            row.document_id,
            row.source_provenance_record_id,
            row.source_id,
            row.external_id,
            row.document_number,
            row.title,
            row.canonical_url,
            row.locator,
            row.content_text,
        )
        for row in rows
    )


@pytest.mark.asyncio
async def test_load_reconstructs_caller_order_and_returns_exact_provenance() -> None:
    run_id = uuid4()
    first = _row(run_id=run_id, provenance_id=uuid4(), text="  first evidence  ")
    second_provenance = uuid4()
    second = _row(run_id=run_id, provenance_id=second_provenance, text=" second evidence ")
    session = _Session(_Result(_as_result_rows((second, first))))
    adapter = PostgresGroundingEvidenceAdapter(  # type: ignore[arg-type]
        lambda: session, _settings(total_evidence_max_chars=40)
    )

    evidence = await adapter.load(
        GroundingEvidenceRequest(
            retrieval_run_id=run_id, citation_ids=(first.citation_id, second.citation_id)
        )
    )

    assert session.statement_count == 1
    assert tuple(item.citation.citation_id for item in evidence.excerpts) == (
        first.citation_id,
        second.citation_id,
    )
    assert evidence.excerpts[1].citation.source_provenance_record_id == second_provenance
    assert tuple(item.text for item in evidence.excerpts) == ("first evidence", "second evidence")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ("missing", "foreign", "version_mismatch"))
async def test_load_fails_closed_for_missing_foreign_or_mismatched_evidence(case: str) -> None:
    run_id = uuid4()
    expected = _row(run_id=run_id)
    if case == "missing":
        rows: tuple[_GroundingRow, ...] = ()
    elif case == "foreign":
        rows = (_row(citation_id=expected.citation_id, run_id=uuid4()),)
    else:
        rows = (
            _row(
                citation_id=expected.citation_id,
                run_id=run_id,
                document_version_id=uuid4(),
                version_id=uuid4(),
            ),
        )
    session = _Session(_Result(_as_result_rows(rows)))
    adapter = PostgresGroundingEvidenceAdapter(lambda: session, _settings())  # type: ignore[arg-type]

    with pytest.raises(ChatError) as failure:
        await adapter.load(
            GroundingEvidenceRequest(retrieval_run_id=run_id, citation_ids=(expected.citation_id,))
        )

    assert failure.value.code is ChatErrorCode.GROUNDING_FAILURE
    assert session.statement_count == 1


@pytest.mark.asyncio
async def test_load_rejects_request_bounds_before_database_access() -> None:
    session = _Session(_Result(()))
    adapter = PostgresGroundingEvidenceAdapter(lambda: session, _settings(max_citations=1))  # type: ignore[arg-type]

    with pytest.raises(ChatError) as maximum:
        await adapter.load(
            GroundingEvidenceRequest(retrieval_run_id=uuid4(), citation_ids=(uuid4(), uuid4()))
        )
    assert maximum.value.code is ChatErrorCode.GROUNDING_FAILURE
    assert session.statement_count == 0

    too_small = PostgresGroundingEvidenceAdapter(
        lambda: session, _settings(total_evidence_max_chars=1)
    )  # type: ignore[arg-type]
    with pytest.raises(ChatError) as budget:
        await too_small.load(
            GroundingEvidenceRequest(retrieval_run_id=uuid4(), citation_ids=(uuid4(), uuid4()))
        )
    assert budget.value.code is ChatErrorCode.GROUNDING_FAILURE
    assert session.statement_count == 0


@pytest.mark.asyncio
async def test_load_round_robins_clipping_in_caller_order() -> None:
    run_id = uuid4()
    first = _row(run_id=run_id, text="abcdefghij")
    second = _row(run_id=run_id, text="klmnopqrst")
    session = _Session(_Result(_as_result_rows((first, second))))
    adapter = PostgresGroundingEvidenceAdapter(
        lambda: session,
        _settings(excerpt_max_chars=10, total_evidence_max_chars=7),
    )  # type: ignore[arg-type]

    evidence = await adapter.load(
        GroundingEvidenceRequest(
            retrieval_run_id=run_id, citation_ids=(first.citation_id, second.citation_id)
        )
    )

    assert tuple(item.text for item in evidence.excerpts) == ("abcd", "klm")
    assert sum(len(item.text) for item in evidence.excerpts) == 7


@pytest.mark.asyncio
async def test_load_normalizes_unexpected_failures_without_sentinel_leak() -> None:
    sentinel = "SENTINEL query identifier and excerpt"
    session = _Session(RuntimeError(sentinel))
    adapter = PostgresGroundingEvidenceAdapter(lambda: session, _settings())  # type: ignore[arg-type]

    with pytest.raises(ChatError) as failure:
        await adapter.load(
            GroundingEvidenceRequest(retrieval_run_id=uuid4(), citation_ids=(uuid4(),))
        )

    assert str(failure.value) == ChatErrorCode.GROUNDING_FAILURE.value
    assert sentinel not in str(failure.value)
