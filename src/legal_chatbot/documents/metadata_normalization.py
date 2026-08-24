"""Source-neutral canonical keys for derived legal-document metadata."""

from __future__ import annotations

import unicodedata

_DASH_TRANSLATION = str.maketrans({character: "-" for character in "‐‑‒–—"})
_MAX_DOCUMENT_NUMBER_CHARS = 256


def normalize_document_number(value: str | None) -> str | None:
    """Return a bounded canonical lookup key without changing the source value.

    The key is NFC/casefolded, normalizes common Unicode dashes, and removes every
    Unicode whitespace character. It intentionally has no source or benchmark rules.
    """

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("document number must be a string or None")
    normalized = unicodedata.normalize("NFC", value).strip().casefold().translate(_DASH_TRANSLATION)
    normalized = "".join(character for character in normalized if not character.isspace())
    if not normalized:
        return None
    if len(normalized) > _MAX_DOCUMENT_NUMBER_CHARS:
        raise ValueError("normalized document number must not exceed 256 characters")
    return normalized
