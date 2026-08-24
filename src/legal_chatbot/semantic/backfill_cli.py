"""CLI entrypoint for an explicitly invoked offline semantic backfill."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence

from legal_chatbot.core.config import Settings
from legal_chatbot.core.logging import configure_logging
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.documents.semantic_embedding_repository import SemanticEmbeddingRepository
from legal_chatbot.semantic.backfill import (
    SemanticBackfillProgress,
    SemanticBackfillResult,
    SemanticBackfillService,
)
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.errors import SemanticError
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


async def _emit_progress(progress: SemanticBackfillProgress) -> None:
    """Emit only source labels and counts, never chunk IDs or text."""

    _emit(
        {
            "event": "semantic_backfill_progress",
            "inserted": progress.inserted,
            "source_counts": progress.source_counts,
        }
    )


def _coverage_payload(result: SemanticBackfillResult) -> dict[str, object]:
    return {
        source: {"eligible": eligible, "semantic_ready": ready}
        for source, (eligible, ready) in result.coverage.items()
    }


async def run() -> int:
    """Run the bounded offline lane and dispose the database engine on every outcome."""

    try:
        app_settings = Settings()  # type: ignore[call-arg]
        semantic_settings = SemanticSettings()
        configure_logging(app_settings.log_level)
    except Exception:
        _emit({"event": "semantic_backfill_failed", "error": "invalid_configuration"})
        return 2

    engine = create_engine(app_settings)
    try:
        repository = SemanticEmbeddingRepository(
            create_session_factory(engine), semantic_settings.backfill_source_ids
        )
        service = SemanticBackfillService(
            repository,
            FastEmbedSemanticAdapter(semantic_settings),
            batch_size=semantic_settings.backfill_batch_size,
        )
        result = await service.run(_emit_progress)
    except SemanticError as error:
        _emit({"event": "semantic_backfill_failed", "error": error.code.value})
        return 1
    except Exception:
        _emit({"event": "semantic_backfill_failed", "error": "persistence_failure"})
        return 1
    finally:
        await engine.dispose()

    _emit(
        {
            "event": "semantic_backfill_complete",
            "inserted": result.inserted,
            "coverage": _coverage_payload(result),
        }
    )
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backfill pinned offline semantic embeddings")
    parser.parse_args(argv)
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
