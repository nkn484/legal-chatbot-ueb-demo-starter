"""CLI entrypoint for the explicitly invoked pinned semantic model prefetch."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.errors import SemanticError
from legal_chatbot.semantic.prefetch import prefetch_model, prefetch_summary


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def run() -> int:
    """Prefetch and validate without emitting paths, artifacts, or content."""

    try:
        settings = SemanticSettings()
        prefetch_model(settings.model_path)
    except SemanticError as error:
        _emit({"event": "semantic_prefetch_failed", "error": error.code.value})
        return 1
    except Exception:
        _emit({"event": "semantic_prefetch_failed", "error": "model_unavailable"})
        return 1
    _emit(prefetch_summary())
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Provide a conventional CLI signature while accepting no user text."""

    parser = argparse.ArgumentParser(description="Prefetch pinned offline semantic model")
    parser.parse_args(argv)
    raise SystemExit(run())


if __name__ == "__main__":
    main()
