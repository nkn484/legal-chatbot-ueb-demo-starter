"""Deterministic canonical serialization and hashing for validated artifacts."""

from __future__ import annotations

import hashlib
import json

from legal_chatbot.legal_effects.models import ReviewedLegalEffectsArtifact


def canonical_artifact_bytes(artifact: ReviewedLegalEffectsArtifact) -> bytes:
    """Return compact, sorted, UTF-8 JSON for an already validated artifact."""

    payload = artifact.model_dump(mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return serialized.encode("utf-8")


def canonical_artifact_sha256(artifact: ReviewedLegalEffectsArtifact) -> str:
    """Return the importer-trusted SHA-256 of canonical validated artifact data."""

    return hashlib.sha256(canonical_artifact_bytes(artifact)).hexdigest()
