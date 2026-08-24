"""CLI for explicit, content-free document metadata derived-key backfill."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.metadata_backfill import DocumentMetadataBackfill


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


async def run(batch_size: int) -> int:
    engine = None
    try:
        engine = create_engine(Settings())  # type: ignore[call-arg]
        backfill = DocumentMetadataBackfill(create_session_factory(engine))
        result = await backfill.run(batch_size=batch_size)
        _emit(
            {
                "event": "metadata_backfill_complete",
                "scanned": result.scanned,
                "updated": result.updated,
            }
        )
        return 0
    except Exception:
        _emit({"event": "metadata_backfill_failed", "error": "metadata_backfill_failed"})
        return 1
    finally:
        if engine is not None:
            await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill canonical document metadata keys")
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args(argv)
    raise SystemExit(asyncio.run(run(args.batch_size)))


if __name__ == "__main__":
    main()
