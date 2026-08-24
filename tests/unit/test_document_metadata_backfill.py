"""Bounded derived-key backfill tests without document evidence retention."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from legal_chatbot.documents.metadata_backfill import DocumentMetadataBackfill


class _Result:
    rowcount = 1


class _Session:
    def __init__(self) -> None:
        self.updated: list[object] = []

    async def execute(self, statement):
        self.updated.append(statement)
        return _Result()

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


class _Factory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[_Session]:
        yield self.session


@pytest.mark.asyncio
async def test_document_metadata_backfill_is_bounded_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = uuid4(), uuid4()
    session = _Session()
    repository = DocumentMetadataBackfill(_Factory(session))  # type: ignore[arg-type]
    batches = [((first, "2725 /QĐ– ĐHKT"), (second, "12/2025/QH15")), ()]

    async def next_batch(cursor, batch_size):
        del cursor
        assert batch_size == 2
        return batches.pop(0)

    monkeypatch.setattr(repository, "_next_batch", next_batch)
    result = await repository.run(batch_size=2)
    assert result.scanned == result.updated == 2
    assert len(session.updated) == 2
    assert all("document_number_normalized" in str(statement) for statement in session.updated)
    with pytest.raises(ValueError, match="500"):
        await repository.run(batch_size=501)
