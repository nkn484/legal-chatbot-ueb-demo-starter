"""Strict parser for bounded LLM legal-question analysis proposals."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .models import LegalQuestionAnalysisProposal


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError
        value[key] = item
    return value


class StrictLegalQuestionAnalysisParser:
    """Accept only the exact proposal schema and reject every other provider output."""

    _KEYS = frozenset(
        {
            "main_intent",
            "legal_actor",
            "legal_action_event",
            "explicit_time",
            "legal_topics",
            "ambiguity",
            "sub_intents",
            "preferred_source_tiers",
            "retrieval_concepts",
        }
    )
    _SUB_INTENT_KEYS = frozenset({"description", "retrieval_concepts", "preferred_source_tiers"})

    def parse(self, output: str) -> LegalQuestionAnalysisProposal:
        try:
            if not isinstance(output, str) or not output.strip().startswith("{"):
                raise ValueError
            decoded = json.loads(output, object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(decoded, dict) or set(decoded) != self._KEYS:
                raise ValueError
            if not isinstance(decoded["sub_intents"], list):
                raise ValueError
            if any(
                not isinstance(item, dict) or set(item) != self._SUB_INTENT_KEYS
                for item in decoded["sub_intents"]
            ):
                raise ValueError
            return LegalQuestionAnalysisProposal.model_validate(decoded)
        except Exception:
            raise ValueError("legal question analyzer output is invalid") from None

    def classify_rejection(self, output: str) -> str:
        """Return a content-free parser failure code for evaluation diagnostics only."""

        try:
            if not isinstance(output, str) or not output.strip().startswith("{"):
                return "JSON_SYNTAX"
            decoded = json.loads(output, object_pairs_hook=_reject_duplicate_keys)
        except _DuplicateJsonKeyError:
            return "DUPLICATE_KEY"
        except (TypeError, json.JSONDecodeError):
            return "JSON_SYNTAX"
        if not isinstance(decoded, dict) or set(decoded) != self._KEYS:
            return "ROOT_OR_KEYSET"
        sub_intents = decoded.get("sub_intents")
        if not isinstance(sub_intents, list) or any(
            not isinstance(item, dict) or set(item) != self._SUB_INTENT_KEYS for item in sub_intents
        ):
            return "SUB_INTENT_SHAPE"
        try:
            LegalQuestionAnalysisProposal.model_validate(decoded)
        except ValidationError as error:
            error_types = {str(item.get("type", "unknown")).upper() for item in error.errors()}
            return "SCHEMA_" + "_".join(sorted(error_types))
        return "UNKNOWN"


__all__ = ["StrictLegalQuestionAnalysisParser"]
