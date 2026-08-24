"""Shared, content-free validation helpers for reviewed legal-effects records."""

from __future__ import annotations

import unicodedata
from typing import Any


def normalize_locator(value: str) -> str:
    """Normalize a structured locator label without inspecting source content."""

    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def locator_matches(locator: dict[str, Any] | None, kind: str, value: str) -> bool:
    """Match only a chunk's structured locator metadata, never chunk content."""

    if not isinstance(locator, dict) or not isinstance(locator.get("kind"), str):
        return False
    if locator["kind"].casefold() != kind.casefold():
        return False
    expected = normalize_locator(value)
    return any(
        isinstance(candidate, str) and normalize_locator(candidate) == expected
        for candidate in (locator.get("label"), locator.get("value"))
    )
