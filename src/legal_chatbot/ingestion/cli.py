"""One-off command for running the bounded source ingestion pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from importlib import import_module
from typing import Any

from legal_chatbot.core.config import Settings
from legal_chatbot.core.logging import configure_logging
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.ingestion.chunking import DeterministicChunker
from legal_chatbot.ingestion.config import IngestionSettings
from legal_chatbot.ingestion.embedding import LocalHashEmbeddingAdapter
from legal_chatbot.ingestion.normalization import HTMLNormalizer
from legal_chatbot.ingestion.service import IngestionService
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.errors import SourceError
from legal_chatbot.sources.models import SourceErrorCode
from legal_chatbot.sources.registry import create_source, load_registry


def _safe_error(error: Exception) -> str:
    """Return only a normalized public error code, never exception details."""
    if isinstance(error, SourceError):
        return error.code.value
    return "ingestion_failed"


def _safe_source_id(value: str) -> str:
    """Restrict emitted source labels to fixed registry-like identifiers."""
    normalized = value.strip().upper()
    if (
        not normalized
        or len(normalized) > 32
        or not normalized.isascii()
        or not normalized.isalnum()
    ):
        return "unknown"
    return normalized


def _result_payload(result: Any, source_id: str) -> dict[str, object]:
    """Emit only operational result fields; never document evidence or DSNs."""
    return {
        "event": "ingestion_result",
        "source": source_id,
        "document_id": str(result.document_id),
        "document_version_id": str(result.document_version_id),
        "outcome": result.outcome.value,
        "block_count": result.block_count,
        "chunk_count": result.chunk_count,
        "embedding_count": result.embedding_count,
        "embedding_model_id": result.embedding_model_id,
        "semantic_ready": result.semantic_ready,
    }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


async def run(source_id: str) -> int:
    """Run all allowed references for a registry source and close every resource."""
    source_id = _safe_source_id(source_id)

    try:
        settings = Settings()  # type: ignore[call-arg]
        source_settings = SourceSettings()
        ingestion_settings = IngestionSettings()
        configure_logging(settings.log_level)
        if source_id == "VBQPPL" and not source_settings.vbqppl_live_ingestion_enabled:
            _emit(
                {
                    "event": "ingestion_error",
                    "source": source_id,
                    "error": "live_ingestion_disabled",
                }
            )
            _emit(
                {
                    "event": "ingestion_summary",
                    "source": source_id,
                    "created": 0,
                    "unchanged": 0,
                    "failed": 0,
                }
            )
            return 2
        registry_data = load_registry(source_settings.registry_path)
        if registry_data.get(source_id) is None:
            raise SourceError(
                code=SourceErrorCode.SOURCE_NOT_CONFIGURED,
                source_id=source_id or "unknown",
                operation="ingest",
            )
        # This module arrives with the persistence milestone. Keep CLI imports lazy so
        # source and pure-ingestion code remain usable when that milestone is not installed.
        repository_module = import_module("legal_chatbot.documents.repository")
        document_repository = repository_module.DocumentRepository
    except Exception as error:
        _emit(
            {
                "event": "ingestion_error",
                "source": source_id or "unknown",
                "error": _safe_error(error),
            }
        )
        _emit(
            {
                "event": "ingestion_summary",
                "source": source_id or "unknown",
                "created": 0,
                "unchanged": 0,
                "failed": 1,
            }
        )
        return 2

    engine = create_engine(settings)
    source = None
    created = unchanged = failed = 0
    try:
        source = create_source(source_id, source_settings, registry_data)
        repository = document_repository(create_session_factory(engine))
        service = IngestionService(
            repository,
            HTMLNormalizer(),
            DeterministicChunker(ingestion_settings),
            LocalHashEmbeddingAdapter(ingestion_settings),
            ingestion_settings,
        )
        try:
            refs = await source.list_documents()
        except Exception as error:
            _emit({"event": "ingestion_error", "source": source_id, "error": _safe_error(error)})
            failed = 1
            return 1

        for ref in refs:
            try:
                result = await service.ingest(source, ref)
            except Exception as error:
                failed += 1
                _emit(
                    {"event": "ingestion_error", "source": source_id, "error": _safe_error(error)}
                )
                continue
            _emit(_result_payload(result, source_id))
            if result.outcome.value == "created":
                created += 1
            else:
                unchanged += 1
        return 1 if failed else 0
    finally:
        _emit(
            {
                "event": "ingestion_summary",
                "source": source_id,
                "created": created,
                "unchanged": unchanged,
                "failed": failed,
            }
        )
        if source is not None:
            await source.aclose()
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """Parse CLI arguments and return an OS exit status."""
    parser = argparse.ArgumentParser(description="Ingest allowed legal source documents")
    parser.add_argument("--source", required=True, help="Registry source ID, for example VBQPPL")
    arguments = parser.parse_args(argv)
    raise SystemExit(asyncio.run(run(arguments.source)))


if __name__ == "__main__":
    main()
