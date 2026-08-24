"""Explicit bounded VBQPPL discovery command; never accepts document-number input."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

from legal_chatbot.core.logging import configure_logging
from legal_chatbot.sources.config import SourceSettings
from legal_chatbot.sources.discovery import discover_manifest
from legal_chatbot.sources.registry import create_discovery_source, load_manifest, load_registry


def _emit(payload: object, output_path: Path | None) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if output_path is None:
        print(serialized)
    else:
        output_path.write_text(serialized + "\n", encoding="utf-8")


async def run(output_path: Path | None = None) -> int:
    """Discover only SOAP numbers pre-authorized by the read manifest."""
    try:
        settings = SourceSettings()
        configure_logging("INFO")
        manifest = load_manifest(settings.vbqppl_read_manifest_path)
        adapter = create_discovery_source(settings, load_registry(settings.registry_path), manifest)
    except Exception:
        _emit({"event": "discovery_error", "error": "discovery_configuration_failed"}, output_path)
        return 2

    try:
        outcomes = await discover_manifest(adapter, manifest)
    finally:
        await adapter.aclose()
    success_count = sum(outcome.success for outcome in outcomes)
    failure_count = len(outcomes) - success_count
    _emit(
        {
            "event": "discovery_results",
            "failure_count": failure_count,
            "outcomes": [outcome.payload() for outcome in outcomes],
            "success_count": success_count,
        },
        output_path,
    )
    return 1 if failure_count else 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Discover only manifest-approved VBQPPL numbers")
    parser.add_argument(
        "--output", type=Path, help="Explicit file path for sanitized candidate JSON"
    )
    arguments = parser.parse_args(argv)
    raise SystemExit(asyncio.run(run(arguments.output)))


if __name__ == "__main__":
    main()
