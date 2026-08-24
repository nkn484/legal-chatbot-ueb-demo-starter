"""Strict, bounded, in-memory parsing for reviewed legal-effects artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from legal_chatbot.legal_effects.constants import MAX_ARTIFACT_BYTES
from legal_chatbot.legal_effects.errors import LegalEffectsArtifactError, LegalEffectsErrorCode
from legal_chatbot.legal_effects.models import ReviewedLegalEffectsArtifact


class _DuplicateJsonKeyError(ValueError):
    """Internal sentinel for a structurally ambiguous JSON object."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _reject_non_json_constant(_: str) -> None:
    raise ValueError


def _decode_json(text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_json_constant,
        )
    except _DuplicateJsonKeyError:
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.DUPLICATE_JSON_KEY) from None
    except (TypeError, ValueError, json.JSONDecodeError):
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.INVALID_JSON) from None
    if not isinstance(value, dict):
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.INVALID_JSON)
    return value


def _check_size(value: bytes) -> None:
    if len(value) > MAX_ARTIFACT_BYTES:
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.ARTIFACT_TOO_LARGE)


def _encode_text(text: str) -> bytes:
    try:
        return text.encode("utf-8")
    except UnicodeEncodeError:
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.INVALID_JSON) from None


def parse_reviewed_legal_effects_artifact(
    raw_artifact: bytes | str | Mapping[str, Any],
) -> ReviewedLegalEffectsArtifact:
    """Parse a bounded bytes/string/mapping artifact without I/O or data-leaking errors."""

    if isinstance(raw_artifact, bytes):
        _check_size(raw_artifact)
        try:
            payload = _decode_json(raw_artifact.decode("utf-8"))
        except UnicodeDecodeError:
            raise LegalEffectsArtifactError(LegalEffectsErrorCode.INVALID_JSON) from None
    elif isinstance(raw_artifact, str):
        _check_size(_encode_text(raw_artifact))
        payload = _decode_json(raw_artifact)
    elif isinstance(raw_artifact, Mapping):
        try:
            serialized = json.dumps(
                raw_artifact, ensure_ascii=False, separators=(",", ":"), allow_nan=False
            )
            encoded = serialized.encode("utf-8")
        except (TypeError, UnicodeEncodeError, ValueError):
            raise LegalEffectsArtifactError(LegalEffectsErrorCode.UNSUPPORTED_INPUT) from None
        _check_size(encoded)
        payload = dict(raw_artifact)
    else:
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.UNSUPPORTED_INPUT)

    try:
        return ReviewedLegalEffectsArtifact.model_validate(payload)
    except ValidationError:
        raise LegalEffectsArtifactError(LegalEffectsErrorCode.INVALID_ARTIFACT) from None
