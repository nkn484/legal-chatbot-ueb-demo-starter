"""Strict parser for proposal-only P4 authority roles."""

import json

from .models import AuthorityRoleProposal


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


__all__ = ["StrictAuthorityProposalParser"]
