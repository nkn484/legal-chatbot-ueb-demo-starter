"""Strict parser for P11 reviewer proposals."""

import json
from typing import Any

from .models import ReviewProposal


class _DuplicateJsonKeyError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKeyError
        value[key] = item
    return value


class StrictLegalAnswerReviewParser:
    """Accept only index-based P11 findings; free text and foreign IDs are rejected."""

    _ROOT_KEYS = frozenset({"decision", "findings"})
    _FINDING_KEYS = frozenset({"code", "claim_indices", "sub_intent_indices", "evidence_indices"})

    def parse(
        self,
        output: str,
        *,
        claim_count: int,
        sub_intent_count: int,
        evidence_count: int,
    ) -> ReviewProposal:
        try:
            if not isinstance(output, str) or not output.strip().startswith("{"):
                raise ValueError
            value = json.loads(output, object_pairs_hook=_reject_duplicate_keys)
            if not isinstance(value, dict) or set(value) != self._ROOT_KEYS:
                raise ValueError
            findings = value["findings"]
            if not isinstance(findings, list) or any(
                not isinstance(item, dict) or set(item) != self._FINDING_KEYS for item in findings
            ):
                raise ValueError
            proposal = ReviewProposal.model_validate(value)
            for finding in proposal.findings:
                if (
                    any(index >= claim_count for index in finding.claim_indices)
                    or any(index >= sub_intent_count for index in finding.sub_intent_indices)
                    or any(index >= evidence_count for index in finding.evidence_indices)
                ):
                    raise ValueError
            return proposal
        except Exception:
            raise ValueError("legal answer reviewer output is invalid") from None


__all__ = ["StrictLegalAnswerReviewParser"]
