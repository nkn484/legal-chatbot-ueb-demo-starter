"""Sequential resumable processing of every automatically eligible corpus record."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Sequence

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.demo_corpus.cli import run as run_stage
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.documents.corpus_catalog_repository import CorpusCatalogRepository

_SOURCES = ("UEB", "VNU", "VBQPPL")


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), flush=True)


async def _reset_transient_failures() -> int:
    settings = Settings()  # type: ignore[call-arg]
    corpus_settings = DemoCorpusSettings()
    engine = create_engine(settings)
    repository = CorpusCatalogRepository(create_session_factory(engine))
    try:
        return await repository.reset_retryable_failures(corpus_settings.dataset_id)
    finally:
        await engine.dispose()


async def _final_summary() -> dict[str, object]:
    settings = Settings()  # type: ignore[call-arg]
    corpus_settings = DemoCorpusSettings()
    engine = create_engine(settings)
    repository = CorpusCatalogRepository(create_session_factory(engine))
    try:
        by_source = await repository.summary_by_source(corpus_settings.dataset_id)
        return {
            "dataset_id": corpus_settings.dataset_id,
            "by_source": by_source,
            "total": sum(count for values in by_source.values() for count in values.values()),
        }
    finally:
        await engine.dispose()


async def main_async(*, stop_after_ocr: str = "VBQPPL") -> int:
    reset_count = await _reset_transient_failures()
    _emit({"event": "demo_corpus_pipeline_retry_reset", "count": reset_count})
    stage_failures = 0

    os.environ["DEMO_CORPUS_OCR_ENABLED"] = "false"
    for source_id in _SOURCES:
        _emit(
            {
                "event": "demo_corpus_pipeline_stage",
                "stage": "native",
                "source": source_id,
                "status": "starting",
            }
        )
        try:
            code = await run_stage(
                source_id=source_id,
                native_text_only=True,
                progress_every=1,
            )
        except Exception:
            code = 2
        stage_failures += int(code != 0)
        _emit(
            {
                "event": "demo_corpus_pipeline_stage",
                "stage": "native",
                "source": source_id,
                "status": "completed",
                "exit_code": code,
            }
        )

    os.environ["DEMO_CORPUS_OCR_ENABLED"] = "true"
    for source_id in _SOURCES:
        _emit(
            {
                "event": "demo_corpus_pipeline_stage",
                "stage": "ocr",
                "source": source_id,
                "status": "starting",
            }
        )
        try:
            code = await run_stage(
                source_id=source_id,
                ocr_only=True,
                progress_every=1,
            )
        except Exception:
            code = 2
        stage_failures += int(code != 0)
        _emit(
            {
                "event": "demo_corpus_pipeline_stage",
                "stage": "ocr",
                "source": source_id,
                "status": "completed",
                "exit_code": code,
            }
        )
        if source_id == stop_after_ocr:
            _emit(
                {
                    "event": "demo_corpus_pipeline_paused",
                    "after_stage": "ocr",
                    "after_source": source_id,
                }
            )
            break

    summary = await _final_summary()
    _emit(
        {
            "event": "demo_corpus_pipeline_complete",
            "stage_failures": stage_failures,
            **summary,
        }
    )
    return 1 if stage_failures else 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Process the resumable demo corpus pipeline")
    parser.add_argument(
        "--stop-after-ocr",
        choices=_SOURCES,
        default="VBQPPL",
        help="Exit cleanly after completing OCR for this source",
    )
    args = parser.parse_args(argv)
    raise SystemExit(asyncio.run(main_async(stop_after_ocr=args.stop_after_ocr)))


if __name__ == "__main__":
    main()
