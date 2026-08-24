"""Focused protocol signature coverage for M06 Phase 1 ports."""

import inspect

from legal_chatbot.chat import (
    CanonicalAnchorResolverPort,
    GroundingEvidencePort,
    ProviderOutputParserPort,
    QueryPlannerPort,
)


def test_grounding_evidence_load_is_async_and_provider_parser_is_sync() -> None:
    assert inspect.iscoroutinefunction(GroundingEvidencePort.load)
    assert not inspect.iscoroutinefunction(ProviderOutputParserPort.parse)
    assert list(inspect.signature(GroundingEvidencePort.load).parameters) == ["self", "request"]
    assert list(inspect.signature(ProviderOutputParserPort.parse).parameters) == ["self", "output"]


def test_planner_and_canonical_anchor_ports_are_narrow_async_contracts() -> None:
    assert inspect.iscoroutinefunction(QueryPlannerPort.plan)
    assert inspect.iscoroutinefunction(CanonicalAnchorResolverPort.resolve)
    assert list(inspect.signature(QueryPlannerPort.plan).parameters) == ["self", "question"]
    assert list(inspect.signature(CanonicalAnchorResolverPort.resolve).parameters) == [
        "self",
        "anchor_mentions",
    ]
