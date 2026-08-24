"""Idempotent PostgreSQL persistence for manual corpus catalog state."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.demo_corpus.models import (
    CatalogEntry,
    CorpusFileKind,
    CorpusProcessingStatus,
)
from legal_chatbot.documents.orm import CorpusCatalogEntry, CorpusIngestionRun

_TRANSITIONS = {
    CorpusProcessingStatus.DISCOVERED: {
        CorpusProcessingStatus.FILE_DOWNLOADED,
        CorpusProcessingStatus.EXTRACTED,
        CorpusProcessingStatus.OCR_REQUIRED,
        CorpusProcessingStatus.QUARANTINED,
        CorpusProcessingStatus.FAILED,
    },
    CorpusProcessingStatus.FILE_DOWNLOADED: {
        CorpusProcessingStatus.EXTRACTED,
        CorpusProcessingStatus.OCR_REQUIRED,
        CorpusProcessingStatus.QUARANTINED,
        CorpusProcessingStatus.FAILED,
    },
    CorpusProcessingStatus.EXTRACTED: {
        CorpusProcessingStatus.CHUNKED,
        CorpusProcessingStatus.INDEXED,
        CorpusProcessingStatus.QUARANTINED,
        CorpusProcessingStatus.FAILED,
    },
    CorpusProcessingStatus.CHUNKED: {
        CorpusProcessingStatus.INDEXED,
        CorpusProcessingStatus.FAILED,
    },
    CorpusProcessingStatus.OCR_REQUIRED: {
        CorpusProcessingStatus.EXTRACTED,
        CorpusProcessingStatus.QUARANTINED,
        CorpusProcessingStatus.FAILED,
    },
    CorpusProcessingStatus.FILE_PENDING: {CorpusProcessingStatus.DISCOVERED},
    CorpusProcessingStatus.QUARANTINED: {CorpusProcessingStatus.DISCOVERED},
    CorpusProcessingStatus.FAILED: {CorpusProcessingStatus.DISCOVERED},
    CorpusProcessingStatus.INDEXED: set(),
}


def _initial_state(entry: CatalogEntry) -> tuple[CorpusProcessingStatus, str | None]:
    if entry.file_kind is CorpusFileKind.DIRECT_FILE:
        return CorpusProcessingStatus.DISCOVERED, None
    if entry.file_kind is CorpusFileKind.FOLDER:
        return CorpusProcessingStatus.QUARANTINED, "folder_reference"
    return CorpusProcessingStatus.FILE_PENDING, "file_reference_pending"


class CorpusCatalogRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert_entries(self, entries: Sequence[CatalogEntry]) -> int:
        async with self._session_factory.begin() as session:
            for entry in entries:
                status, reason = _initial_state(entry)
                values = {
                    **entry.model_dump(mode="python"),
                    "file_kind": entry.file_kind.value,
                    "processing_status": status.value,
                    "reason_code": reason,
                }
                statement = insert(CorpusCatalogEntry).values(**values)
                excluded = statement.excluded
                statement = statement.on_conflict_do_update(
                    constraint="uq_corpus_catalog_entries_source_row",
                    set_={
                        "external_id": excluded.external_id,
                        "document_number": excluded.document_number,
                        "title": excluded.title,
                        "document_type": excluded.document_type,
                        "issuing_authority": excluded.issuing_authority,
                        "issue_date": excluded.issue_date,
                        "effective_date": excluded.effective_date,
                        "legal_status": excluded.legal_status,
                        "file_label": excluded.file_label,
                        "file_url": excluded.file_url,
                        "file_kind": excluded.file_kind,
                        "record_sha256": excluded.record_sha256,
                        "processing_status": case(
                            (
                                CorpusCatalogEntry.processing_status.in_(
                                    (
                                        CorpusProcessingStatus.FILE_PENDING.value,
                                        CorpusProcessingStatus.QUARANTINED.value,
                                    )
                                )
                                & (excluded.file_kind == CorpusFileKind.DIRECT_FILE.value),
                                CorpusProcessingStatus.DISCOVERED.value,
                            ),
                            else_=CorpusCatalogEntry.processing_status,
                        ),
                        "reason_code": case(
                            (
                                CorpusCatalogEntry.processing_status.in_(
                                    (
                                        CorpusProcessingStatus.FILE_PENDING.value,
                                        CorpusProcessingStatus.QUARANTINED.value,
                                    )
                                )
                                & (excluded.file_kind == CorpusFileKind.DIRECT_FILE.value),
                                None,
                            ),
                            else_=CorpusCatalogEntry.reason_code,
                        ),
                        "updated_at": func.now(),
                    },
                )
                await session.execute(statement)
        return len(entries)

    async def list_processable(
        self,
        dataset_id: str,
        source_id: str | None = None,
        limit: int | None = None,
        *,
        include_discovered: bool = True,
        include_ocr_required: bool = False,
    ) -> tuple[CorpusCatalogEntry, ...]:
        statuses: list[str] = []
        if include_discovered:
            statuses.append(CorpusProcessingStatus.DISCOVERED.value)
        if include_ocr_required:
            statuses.append(CorpusProcessingStatus.OCR_REQUIRED.value)
        if not statuses:
            return ()
        statement = select(CorpusCatalogEntry).where(
            CorpusCatalogEntry.dataset_id == dataset_id,
            CorpusCatalogEntry.processing_status.in_(statuses),
        )
        if source_id is not None:
            statement = statement.where(CorpusCatalogEntry.source_id == source_id)
        statement = statement.order_by(
            CorpusCatalogEntry.source_id,
            CorpusCatalogEntry.sheet_name,
            CorpusCatalogEntry.source_row,
        )
        if limit is not None:
            statement = statement.limit(limit)
        async with self._session_factory() as session:
            return tuple((await session.scalars(statement)).all())

    async def transition(
        self,
        entry_id: UUID,
        status: CorpusProcessingStatus,
        *,
        reason_code: str | None = None,
        file_sha256: str | None = None,
        legal_document_id: UUID | None = None,
        document_version_id: UUID | None = None,
    ) -> None:
        async with self._session_factory.begin() as session:
            current = await session.scalar(
                select(CorpusCatalogEntry.processing_status)
                .where(CorpusCatalogEntry.id == entry_id)
                .with_for_update()
            )
            if current is None:
                raise ValueError("catalog_entry_not_found")
            current_status = CorpusProcessingStatus(current)
            if (
                current_status
                in {
                    CorpusProcessingStatus.INDEXED,
                    CorpusProcessingStatus.QUARANTINED,
                    CorpusProcessingStatus.FAILED,
                }
                and status is not current_status
            ):
                return
            if status != current_status and status not in _TRANSITIONS[current_status]:
                raise ValueError("invalid_catalog_status_transition")
            await session.execute(
                update(CorpusCatalogEntry)
                .where(CorpusCatalogEntry.id == entry_id)
                .values(
                    processing_status=status.value,
                    reason_code=reason_code,
                    file_sha256=file_sha256,
                    legal_document_id=legal_document_id,
                    document_version_id=document_version_id,
                    updated_at=func.now(),
                )
            )

    async def start_run(self, dataset_id: str, mode: str) -> UUID:
        async with self._session_factory.begin() as session:
            run = CorpusIngestionRun(dataset_id=dataset_id, mode=mode, status="RUNNING")
            session.add(run)
            await session.flush()
            return run.id

    async def finish_run(self, run_id: UUID, summary: dict[str, Any]) -> None:
        failed = (
            int(summary.get("failed", 0))
            + int(summary.get("FAILED", 0))
            + int(summary.get("timeout", 0))
        )
        status = "COMPLETED_WITH_FAILURES" if failed else "COMPLETED"
        async with self._session_factory.begin() as session:
            await session.execute(
                update(CorpusIngestionRun)
                .where(CorpusIngestionRun.id == run_id)
                .values(status=status, summary=summary, finished_at=datetime.now(UTC))
            )

    async def update_run_progress(self, run_id: UUID, progress: dict[str, Any]) -> None:
        """Persist a bounded heartbeat without document content, title, or URL."""

        allowed = {
            "processed",
            "total",
            "current_source",
            "current_row",
            "current_document_number",
            "current_outcome",
            "counts",
            "elapsed_seconds",
            "eta_seconds",
            "updated_at",
        }
        if set(progress) - allowed:
            raise ValueError("unsupported_corpus_progress_field")
        async with self._session_factory.begin() as session:
            await session.execute(
                update(CorpusIngestionRun)
                .where(
                    CorpusIngestionRun.id == run_id,
                    CorpusIngestionRun.status == "RUNNING",
                )
                .values(summary=progress)
            )

    async def latest_run(self, dataset_id: str) -> dict[str, Any] | None:
        async with self._session_factory() as session:
            run = await session.scalar(
                select(CorpusIngestionRun)
                .where(CorpusIngestionRun.dataset_id == dataset_id)
                .order_by(CorpusIngestionRun.started_at.desc(), CorpusIngestionRun.id.desc())
                .limit(1)
            )
        if run is None:
            return None
        return {
            "run_id": str(run.id),
            "dataset_id": run.dataset_id,
            "mode": run.mode,
            "status": run.status,
            "summary": run.summary or {},
            "started_at": run.started_at.isoformat(),
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    async def reset_retryable_failures(self, dataset_id: str) -> int:
        """Retry only transient processing failures; never folders or invalid documents."""

        async with self._session_factory.begin() as session:
            result = await session.execute(
                update(CorpusCatalogEntry)
                .where(
                    CorpusCatalogEntry.dataset_id == dataset_id,
                    CorpusCatalogEntry.processing_status == CorpusProcessingStatus.FAILED.value,
                    CorpusCatalogEntry.reason_code.in_(("processing_timeout", "processing_failed")),
                )
                .values(
                    processing_status=CorpusProcessingStatus.DISCOVERED.value,
                    reason_code=None,
                    updated_at=func.now(),
                )
            )
        return int(getattr(result, "rowcount", 0) or 0)

    async def summary(self, dataset_id: str) -> dict[str, int]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(CorpusCatalogEntry.processing_status, func.count())
                    .where(CorpusCatalogEntry.dataset_id == dataset_id)
                    .group_by(CorpusCatalogEntry.processing_status)
                )
            ).all()
        counts = Counter({status: int(count) for status, count in rows})
        counts["total"] = sum(counts.values())
        return dict(counts)

    async def summary_by_source(self, dataset_id: str) -> dict[str, dict[str, int]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        CorpusCatalogEntry.source_id,
                        CorpusCatalogEntry.processing_status,
                        func.count(),
                    )
                    .where(CorpusCatalogEntry.dataset_id == dataset_id)
                    .group_by(
                        CorpusCatalogEntry.source_id,
                        CorpusCatalogEntry.processing_status,
                    )
                    .order_by(
                        CorpusCatalogEntry.source_id,
                        CorpusCatalogEntry.processing_status,
                    )
                )
            ).all()
        output: dict[str, dict[str, int]] = {}
        for source_id, status, count in rows:
            output.setdefault(source_id, {})[status] = int(count)
        return output
