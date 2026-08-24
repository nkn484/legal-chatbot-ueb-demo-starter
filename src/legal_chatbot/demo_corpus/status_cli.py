"""One-shot or watch-mode progress status for demo corpus ingestion."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from datetime import UTC, datetime

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.documents.corpus_catalog_repository import CorpusCatalogRepository


def _is_stale(run: dict[str, object] | None, threshold_seconds: float) -> bool:
    if run is None or run.get("status") != "RUNNING":
        return False
    summary = run.get("summary")
    updated_at = summary.get("updated_at") if isinstance(summary, dict) else None
    timestamp = updated_at if isinstance(updated_at, str) else run.get("started_at")
    if not isinstance(timestamp, str):
        return True
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return True
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return True
    return (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() > threshold_seconds


async def _snapshot(repository: CorpusCatalogRepository, dataset_id: str, stale_after: float):
    run = await repository.latest_run(dataset_id)
    by_source = await repository.summary_by_source(dataset_id)
    total = sum(count for statuses in by_source.values() for count in statuses.values())
    return {
        "event": "demo_corpus_status",
        "dataset_id": dataset_id,
        "catalog_total": total,
        "by_source": by_source,
        "latest_run": run,
        "stale": _is_stale(run, stale_after),
        "observed_at": datetime.now(UTC).isoformat(),
    }


async def run(*, watch_seconds: float | None, stale_after: float) -> int:
    settings = Settings()  # type: ignore[call-arg]
    corpus_settings = DemoCorpusSettings()
    engine = create_engine(settings)
    repository = CorpusCatalogRepository(create_session_factory(engine))
    try:
        while True:
            print(
                json.dumps(
                    await _snapshot(repository, corpus_settings.dataset_id, stale_after),
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
                flush=True,
            )
            if watch_seconds is None:
                return 0
            await asyncio.sleep(watch_seconds)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="View demo corpus processing progress")
    parser.add_argument("--watch", type=float, choices=(2.0, 5.0, 10.0, 30.0))
    parser.add_argument("--stale-after", type=float, default=300.0)
    args = parser.parse_args(argv)
    raise SystemExit(asyncio.run(run(watch_seconds=args.watch, stale_after=args.stale_after)))


if __name__ == "__main__":
    main()
