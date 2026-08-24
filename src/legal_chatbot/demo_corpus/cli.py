"""Manual command for cataloging and processing the approved 1,104-row snapshot corpus."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from time import monotonic
from typing import Any, cast

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.demo_corpus.adapter import ManualSnapshotSourceAdapter
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.demo_corpus.models import CatalogEntry, CorpusProcessingStatus
from legal_chatbot.demo_corpus.pdf import OCRRequiredError, PDFTextExtractor, TesseractOCRAdapter
from legal_chatbot.demo_corpus.workbook import load_demo_catalog
from legal_chatbot.documents.corpus_catalog_repository import CorpusCatalogRepository
from legal_chatbot.documents.repository import DocumentRepository
from legal_chatbot.ingestion import (
    DeterministicChunker,
    HTMLNormalizer,
    IngestionService,
    IngestionSettings,
    LocalHashEmbeddingAdapter,
)


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _entry_from_record(record: Any) -> CatalogEntry:
    return CatalogEntry(
        dataset_id=record.dataset_id,
        source_id=record.source_id,
        workbook_name=record.workbook_name,
        sheet_name=record.sheet_name,
        source_row=record.source_row,
        external_id=record.external_id,
        document_number=record.document_number,
        title=record.title,
        document_type=record.document_type,
        issuing_authority=record.issuing_authority,
        issue_date=record.issue_date,
        effective_date=record.effective_date,
        legal_status=record.legal_status,
        file_label=record.file_label,
        file_url=record.file_url,
        file_kind=record.file_kind,
        record_sha256=record.record_sha256,
    )


def _progress_payload(
    *,
    processed: int,
    total: int,
    entry: CatalogEntry | None,
    outcome: str | None,
    outcomes: Counter[str],
    started_at: float,
) -> dict[str, Any]:
    elapsed = max(0.0, monotonic() - started_at)
    eta = None
    if processed > 0 and processed < total:
        eta = (elapsed / processed) * (total - processed)
    return {
        "processed": processed,
        "total": total,
        "current_source": entry.source_id if entry else None,
        "current_row": entry.source_row if entry else None,
        "current_document_number": entry.document_number if entry else None,
        "current_outcome": outcome,
        "counts": dict(outcomes),
        "elapsed_seconds": round(elapsed, 1),
        "eta_seconds": round(eta, 1) if eta is not None else None,
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def run(
    *,
    catalog_only: bool = False,
    dry_run: bool = False,
    source_id: str | None = None,
    limit: int | None = None,
    native_text_only: bool = False,
    ocr_only: bool = False,
    progress_every: int = 1,
) -> int:
    if native_text_only and ocr_only:
        _emit({"event": "demo_corpus_error", "error": "conflicting_processing_modes"})
        return 2
    if ocr_only and not DemoCorpusSettings().ocr_enabled:
        _emit({"event": "demo_corpus_error", "error": "ocr_only_requires_ocr_enabled"})
        return 2
    corpus_settings = DemoCorpusSettings()
    entries = load_demo_catalog(corpus_settings.data_path, dataset_id=corpus_settings.dataset_id)
    counts = Counter(entry.source_id for entry in entries)
    if len(entries) != 1_104:
        _emit(
            {"event": "demo_corpus_error", "error": "catalog_count_mismatch", "count": len(entries)}
        )
        return 2
    _emit({"event": "demo_corpus_catalog", "total": len(entries), "sources": dict(counts)})
    if dry_run:
        return 0

    app_settings = Settings()  # type: ignore[call-arg]
    engine = create_engine(app_settings)
    session_factory = create_session_factory(engine)
    catalog_repository = CorpusCatalogRepository(session_factory)
    mode = "catalog_only"
    if not catalog_only:
        stage = "ocr" if ocr_only else "native" if native_text_only else "process"
        mode = f"{stage}:{source_id or 'ALL'}"
    run_id = await catalog_repository.start_run(corpus_settings.dataset_id, mode)
    outcomes: Counter[str] = Counter()
    progress_started_at = monotonic()
    last_progress: dict[str, Any] = {}
    try:
        await catalog_repository.upsert_entries(entries)
        if catalog_only:
            summary = await catalog_repository.summary(corpus_settings.dataset_id)
            await catalog_repository.finish_run(run_id, summary)
            _emit({"event": "demo_corpus_summary", **summary})
            return 0

        ingestion_settings = IngestionSettings()
        ingestion = IngestionService(
            cast(Any, DocumentRepository(session_factory)),
            HTMLNormalizer(),
            DeterministicChunker(ingestion_settings),
            LocalHashEmbeddingAdapter(ingestion_settings),
            ingestion_settings,
        )
        ocr = (
            TesseractOCRAdapter(
                executable=corpus_settings.ocr_executable,
                language=corpus_settings.ocr_language,
            )
            if corpus_settings.ocr_enabled
            else None
        )
        extractor = PDFTextExtractor(ocr)
        processable = await catalog_repository.list_processable(
            corpus_settings.dataset_id,
            source_id=source_id,
            limit=limit,
            include_discovered=not ocr_only,
            include_ocr_required=corpus_settings.ocr_enabled or ocr_only,
        )
        total_processable = len(processable)
        await catalog_repository.update_run_progress(
            run_id,
            _progress_payload(
                processed=0,
                total=total_processable,
                entry=None,
                outcome="starting",
                outcomes=outcomes,
                started_at=progress_started_at,
            ),
        )
        parsed_by_id = {entry.external_id: entry for entry in entries}
        adapters: dict[str, ManualSnapshotSourceAdapter] = {}
        try:
            for processed, record in enumerate(processable, start=1):
                entry = parsed_by_id.get(record.external_id) or _entry_from_record(record)
                adapter = adapters.get(entry.source_id)
                if adapter is None:
                    adapter = ManualSnapshotSourceAdapter(
                        entry.source_id, entries, corpus_settings, extractor
                    )
                    adapters[entry.source_id] = adapter
                ref = next(
                    value
                    for value in await adapter.list_documents()
                    if value.external_id == entry.external_id
                )
                try:
                    snapshot, asset = await asyncio.wait_for(
                        adapter.fetch_document_artifact(ref),
                        timeout=corpus_settings.processing_timeout_seconds,
                    )
                    await catalog_repository.transition(
                        record.id,
                        CorpusProcessingStatus.EXTRACTED,
                        file_sha256=asset.sha256,
                    )
                    result = await asyncio.wait_for(
                        ingestion.ingest_snapshot(snapshot),
                        timeout=corpus_settings.processing_timeout_seconds,
                    )
                    await catalog_repository.transition(
                        record.id,
                        CorpusProcessingStatus.INDEXED,
                        file_sha256=asset.sha256,
                        legal_document_id=result.document_id,
                        document_version_id=result.document_version_id,
                    )
                    outcomes["indexed"] += 1
                    outcome = "indexed"
                except TimeoutError:
                    await catalog_repository.transition(
                        record.id,
                        CorpusProcessingStatus.FAILED,
                        reason_code="processing_timeout",
                    )
                    outcomes["timeout"] += 1
                    outcome = "timeout"
                except OCRRequiredError:
                    await catalog_repository.transition(
                        record.id,
                        CorpusProcessingStatus.OCR_REQUIRED,
                        reason_code="ocr_required",
                    )
                    outcomes["ocr_required"] += 1
                    outcome = "ocr_required"
                except ValueError:
                    await catalog_repository.transition(
                        record.id,
                        CorpusProcessingStatus.QUARANTINED,
                        reason_code="document_validation_failed",
                    )
                    outcomes["quarantined"] += 1
                    outcome = "quarantined"
                except Exception:
                    await catalog_repository.transition(
                        record.id,
                        CorpusProcessingStatus.FAILED,
                        reason_code="processing_failed",
                    )
                    outcomes["failed"] += 1
                    outcome = "failed"
                progress = _progress_payload(
                    processed=processed,
                    total=total_processable,
                    entry=entry,
                    outcome=outcome,
                    outcomes=outcomes,
                    started_at=progress_started_at,
                )
                last_progress = progress
                await catalog_repository.update_run_progress(run_id, progress)
                if processed % progress_every == 0 or processed == total_processable:
                    _emit({"event": "demo_corpus_progress", "run_id": str(run_id), **progress})
        finally:
            for adapter in adapters.values():
                await adapter.aclose()
        catalog_summary = await catalog_repository.summary(corpus_settings.dataset_id)
        summary: dict[str, Any] = dict(catalog_summary)
        summary.update(outcomes)
        summary.update(
            {
                "processed": total_processable,
                "batch_total": total_processable,
                "elapsed_seconds": round(monotonic() - progress_started_at, 1),
            }
        )
        await catalog_repository.finish_run(run_id, summary)
        _emit({"event": "demo_corpus_summary", **summary})
        return 1 if outcomes["failed"] else 0
    except Exception:
        failure_summary = dict(last_progress)
        failure_summary.update({"failed": 1, "failure_reason": "batch_interrupted"})
        await catalog_repository.finish_run(run_id, failure_summary)
        raise
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Import the approved manual demo corpus")
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", choices=("VBQPPL", "VNU", "UEB"))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--native-text-only", action="store_true")
    parser.add_argument("--ocr-only", action="store_true")
    parser.add_argument("--progress-every", type=int, default=1, choices=range(1, 101))
    args = parser.parse_args(argv)
    raise SystemExit(
        asyncio.run(
            run(
                catalog_only=args.catalog_only,
                dry_run=args.dry_run,
                source_id=args.source,
                limit=args.limit,
                native_text_only=args.native_text_only,
                ocr_only=args.ocr_only,
                progress_every=args.progress_every,
            )
        )
    )


if __name__ == "__main__":
    main()
