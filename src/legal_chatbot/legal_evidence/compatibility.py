"""Explicit mappings from legacy quality-retrieval labels to proposal-only contracts."""

from __future__ import annotations

from .models import AuthorityRole, CoverageState


def map_legacy_authority_role(value: object) -> AuthorityRole:
    """Map legacy selection labels without promoting them to verified authority."""

    normalized = str(getattr(value, "value", value)).strip().upper()
    mapping = {
        "DIRECT_AUTHORITY": AuthorityRole.GOVERNING,
        "IMPLEMENTING_OR_INTERNAL_RULE": AuthorityRole.IMPLEMENTING,
        "SUPPLEMENTARY_AUTHORITY": AuthorityRole.SUPPLEMENTARY,
        "BACKGROUND": AuthorityRole.BACKGROUND,
        "IRRELEVANT": AuthorityRole.IRRELEVANT,
    }
    try:
        return mapping[normalized]
    except KeyError as error:
        raise ValueError("unknown legacy authority role") from error


def map_legacy_coverage_state(value: object) -> CoverageState:
    """Map legacy coverage names while preserving unresolved or ambiguous evidence."""

    normalized = str(getattr(value, "value", value)).strip().upper()
    mapping = {
        "SUPPORTED": CoverageState.SUPPORTED,
        "PARTIALLY_SUPPORTED": CoverageState.PARTIALLY_SUPPORTED,
        "UNSUPPORTED": CoverageState.UNSUPPORTED,
        "AMBIGUOUS": CoverageState.CONFLICT,
        "UNAVAILABLE": CoverageState.UNSUPPORTED,
    }
    try:
        return mapping[normalized]
    except KeyError as error:
        raise ValueError("unknown legacy coverage state") from error


__all__ = ["map_legacy_authority_role", "map_legacy_coverage_state"]
