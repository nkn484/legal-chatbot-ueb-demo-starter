"""CLI entrypoint for explicit pinned reranker artifact prefetching."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from legal_chatbot.reranking.config import RerankerSettings
from legal_chatbot.reranking.errors import RerankerError
from legal_chatbot.reranking.prefetch import prefetch_model, prefetch_summary


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def run() -> int:
    """Prefetch and validate without emitting paths, artifact names, or source text."""

    try:
        settings = RerankerSettings()
        prefetch_model(settings.model_path)
    except RerankerError as error:
        _emit({"event": "reranker_prefetch_failed", "error": error.code.value})
        return 1
    except Exception:
        _emit({"event": "reranker_prefetch_failed", "error": "model_unavailable"})
        return 1
    _emit(prefetch_summary())
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    """Provide a conventional CLI signature while accepting no user text."""

    parser = argparse.ArgumentParser(description="Prefetch pinned offline reranker model")
    parser.parse_args(argv)
    raise SystemExit(run())


if __name__ == "__main__":
    main()
