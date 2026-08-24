"""Pinned, auditable local reranker prefetching with artifact verification."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from legal_chatbot.reranking.constants import (
    ONNX_MODEL_FILE,
    ONNX_MODEL_SHA256,
    ONNX_MODEL_SIZE,
    REQUIRED_MODEL_FILES,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
    RERANKER_PROFILE_ID,
)
from legal_chatbot.reranking.errors import RerankerError, RerankerErrorCode


def validate_model_artifact(model_path: Path) -> None:
    """Fail closed unless each runtime file and the pinned ONNX bytes exist."""

    for required_file in REQUIRED_MODEL_FILES:
        if not (model_path / required_file).is_file():
            raise RerankerError(RerankerErrorCode.MODEL_ARTIFACT_INVALID)
    artifact = model_path / ONNX_MODEL_FILE
    try:
        if artifact.stat().st_size != ONNX_MODEL_SIZE:
            raise RerankerError(RerankerErrorCode.MODEL_ARTIFACT_INVALID)
        digest = sha256()
        with artifact.open("rb") as stream:
            for block in iter(lambda: stream.read(1_048_576), b""):
                digest.update(block)
        if digest.hexdigest() != ONNX_MODEL_SHA256:
            raise RerankerError(RerankerErrorCode.MODEL_ARTIFACT_INVALID)
    except OSError as error:
        raise RerankerError(RerankerErrorCode.MODEL_ARTIFACT_INVALID) from error


def prefetch_model(
    model_path: Path, *, api: Any | None = None, snapshot: Any | None = None
) -> None:
    """Download exactly the pinned revision, then validate only its required files."""

    try:
        if api is None or snapshot is None:
            from huggingface_hub import HfApi, snapshot_download

            api = HfApi() if api is None else api
            snapshot = snapshot_download if snapshot is None else snapshot
        model_info = api.model_info(
            repo_id=RERANKER_MODEL_ID,
            revision=RERANKER_MODEL_REVISION,
            files_metadata=True,
        )
        if getattr(model_info, "sha", None) != RERANKER_MODEL_REVISION:
            raise RerankerError(RerankerErrorCode.MODEL_ARTIFACT_INVALID)
        snapshot(
            repo_id=RERANKER_MODEL_ID,
            revision=RERANKER_MODEL_REVISION,
            local_dir=str(model_path),
            allow_patterns=list(REQUIRED_MODEL_FILES),
        )
        validate_model_artifact(model_path)
    except RerankerError:
        raise
    except Exception as error:
        raise RerankerError(RerankerErrorCode.MODEL_UNAVAILABLE) from error


def prefetch_summary() -> dict[str, object]:
    """Return content-free metadata suitable for the JSON-only CLI output."""

    return {
        "event": "reranker_model_prefetched",
        "model_id": RERANKER_MODEL_ID,
        "profile_id": RERANKER_PROFILE_ID,
        "revision": RERANKER_MODEL_REVISION,
    }
