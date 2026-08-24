"""Content-safe command line entry point for reviewed-effect imports."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from legal_chatbot.core.config import Settings
from legal_chatbot.db.session import create_engine, create_session_factory
from legal_chatbot.legal_effects.constants import MAX_ARTIFACT_BYTES
from legal_chatbot.legal_effects.errors import (
    LegalEffectsArtifactError,
    LegalEffectsImportError,
)
from legal_chatbot.legal_effects.importer import (
    ReviewedLegalEffectsImporter,
    ReviewedLegalEffectsImportResult,
)
from legal_chatbot.legal_effects.parser import parse_reviewed_legal_effects_artifact

CONFIG_FAILURE = 2
PARSER_FAILURE = 3
IMPORT_FAILURE = 4


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _result_payload(result: ReviewedLegalEffectsImportResult) -> dict[str, object]:
    """Return only content-free operation counts and a short artifact hash prefix."""

    return {
        "event": "reviewed_legal_effects_import",
        "status": result.status.value,
        "import_count": result.import_count,
        "family_count": result.family_count,
        "assertion_count": result.assertion_count,
        "event_count": result.event_count,
        "manual_basis_count": result.manual_basis_count,
        "source_fetch_basis_count": result.source_fetch_basis_count,
        "artifact_hash_prefix": result.artifact_hash_prefix,
    }


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import one approved reviewed-effects artifact.")
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--imported-by", required=True)
    return parser.parse_args(argv)


async def run(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        with args.artifact.open("rb") as artifact_file:
            raw_artifact = artifact_file.read(MAX_ARTIFACT_BYTES + 1)
        artifact = parse_reviewed_legal_effects_artifact(raw_artifact)
    except (OSError, LegalEffectsArtifactError):
        _emit({"event": "reviewed_legal_effects_import_error", "error": "parser_failure"})
        return PARSER_FAILURE
    try:
        settings = Settings()  # type: ignore[call-arg]
        engine = create_engine(settings)
    except Exception:
        _emit({"event": "reviewed_legal_effects_import_error", "error": "config_failure"})
        return CONFIG_FAILURE
    try:
        result = await ReviewedLegalEffectsImporter(create_session_factory(engine)).import_artifact(
            artifact, args.imported_by
        )
        _emit(_result_payload(result))
        return 0
    except LegalEffectsImportError as error:
        _emit({"event": "reviewed_legal_effects_import_error", "error": error.code.value})
        return IMPORT_FAILURE
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
