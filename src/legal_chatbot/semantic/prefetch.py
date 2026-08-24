"""Pinned, auditable local model prefetching with artifact verification."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from legal_chatbot.semantic.constants import (
    ONNX_MODEL_FILE,
    ONNX_MODEL_SHA256,
    ONNX_MODEL_SIZE,
    REQUIRED_MODEL_FILES,
    SEMANTIC_MODEL_ID,
    SEMANTIC_MODEL_REVISION,
    SEMANTIC_PROFILE_ID,
)
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode


def validate_model_artifact(model_path: Path) -> None:
    """Fail closed unless every runtime file and the pinned ONNX bytes exist."""

    for required_file in REQUIRED_MODEL_FILES:
        if not (model_path / required_file).is_file():
            raise SemanticError(SemanticErrorCode.MODEL_ARTIFACT_INVALID)
    artifact = model_path / ONNX_MODEL_FILE
    try:
        if artifact.stat().st_size != ONNX_MODEL_SIZE:
            raise SemanticError(SemanticErrorCode.MODEL_ARTIFACT_INVALID)
        digest = sha256()
        with artifact.open("rb") as stream:
            for block in iter(lambda: stream.read(1_048_576), b""):
                digest.update(block)
        if digest.hexdigest() != ONNX_MODEL_SHA256:
            raise SemanticError(SemanticErrorCode.MODEL_ARTIFACT_INVALID)
    except OSError as error:
        raise SemanticError(SemanticErrorCode.MODEL_ARTIFACT_INVALID) from error


def prefetch_model(
    model_path: Path, *, api: Any | None = None, snapshot: Any | None = None
) -> None:
    """Download only the pinned revision, then verify its required local artifact."""

    try:
        if api is None or snapshot is None:
            from huggingface_hub import HfApi, snapshot_download

            api = HfApi() if api is None else api
            snapshot = snapshot_download if snapshot is None else snapshot
        model_info = api.model_info(
            repo_id=SEMANTIC_MODEL_ID,
            revision=SEMANTIC_MODEL_REVISION,
            files_metadata=True,
        )
        if getattr(model_info, "sha", None) != SEMANTIC_MODEL_REVISION:
            raise SemanticError(SemanticErrorCode.MODEL_ARTIFACT_INVALID)
        snapshot(
            repo_id=SEMANTIC_MODEL_ID,
            revision=SEMANTIC_MODEL_REVISION,
            local_dir=str(model_path),
            allow_patterns=list(REQUIRED_MODEL_FILES),
        )
        validate_model_artifact(model_path)
    except SemanticError:
        raise
    except Exception as error:
        raise SemanticError(SemanticErrorCode.MODEL_UNAVAILABLE) from error


def prefetch_summary() -> dict[str, object]:
    """Return content-free metadata suitable for JSON CLI output."""

    return {
        "event": "semantic_model_prefetched",
        "model_id": SEMANTIC_MODEL_ID,
        "profile_id": SEMANTIC_PROFILE_ID,
        "revision": SEMANTIC_MODEL_REVISION,
    }
