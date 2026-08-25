"""Strict parser for bounded LLM legal-question analysis proposals."""

from __future__ import annotations

import json
from typing import Any

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


__all__ = ["StrictLegalQuestionAnalysisParser"]
