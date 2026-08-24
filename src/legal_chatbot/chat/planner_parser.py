"""Fail-closed exact JSON parser for LLM retrieval plans."""

import json
from typing import Any

from legal_chatbot.chat.planner_models import QueryPlannerPlan, validate_query_plan


class _DuplicateJsonKeyError(ValueError):
    """Internal marker for duplicate keys in an otherwise valid JSON object."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


class StrictQueryPlannerParser:
    """Accept one exact JSON plan and reject all unsafe or semantically drifting output."""

    def parse(
        self,
        output: str,
        question: str,
        *,
        max_phrases: int,
        max_expansion_terms: int,
    ) -> QueryPlannerPlan:
        try:
            if not isinstance(output, str) or not output.strip().startswith("{"):
                raise ValueError
            parsed = json.loads(output, object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(parsed, dict) or set(parsed) != {
                "anchor_mentions",
                "key_phrases",
                "expansion_terms",
            }:
                raise ValueError
            if not all(isinstance(parsed[name], list) for name in parsed):
                raise ValueError
            plan = QueryPlannerPlan.model_validate(parsed)
            return validate_query_plan(
                plan,
                question,
                max_phrases=max_phrases,
                max_expansion_terms=max_expansion_terms,
            )
        except Exception:
            raise ValueError("planner output is invalid") from None
