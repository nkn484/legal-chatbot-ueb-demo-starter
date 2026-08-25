"""Strict parser for proposal-only P4 authority roles."""

import json

from .models import AuthorityAssessmentProposal, AuthorityRoleProposal


class StrictAuthorityProposalParser:
    def parse(self, output: str, *, candidate_count: int) -> tuple[AuthorityRoleProposal, ...]:
        try:
            value = json.loads(output)
            if not isinstance(value, dict) or set(value) != {"candidates"}:
                raise ValueError
            raw = value["candidates"]
            if not isinstance(raw, list) or len(raw) != candidate_count:
                raise ValueError
            proposals = tuple(AuthorityRoleProposal.model_validate(item) for item in raw)
            if {item.candidate_index for item in proposals} != set(range(candidate_count)):
                raise ValueError
            return proposals
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("authority proposal output is invalid") from None

    def parse_assessments(
        self, output: str, *, candidate_count: int, sub_intent_count: int
    ) -> tuple[AuthorityAssessmentProposal, ...]:
        try:
            value = json.loads(output)
            if not isinstance(value, dict) or set(value) != {"assessments"}:
                raise ValueError
            raw = value["assessments"]
            expected = candidate_count * sub_intent_count
            if not isinstance(raw, list) or len(raw) != expected:
                raise ValueError
            proposals = tuple(AuthorityAssessmentProposal.model_validate(item) for item in raw)
            pairs = {(item.candidate_index, item.sub_intent_index) for item in proposals}
            if pairs != {
                (candidate_index, sub_intent_index)
                for candidate_index in range(candidate_count)
                for sub_intent_index in range(sub_intent_count)
            }:
                raise ValueError
            return proposals
        except (TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("authority assessment output is invalid") from None


__all__ = ["StrictAuthorityProposalParser"]
