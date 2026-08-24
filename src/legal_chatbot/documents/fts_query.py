"""Pure PostgreSQL tsquery text controls used only by evaluation readers."""

from __future__ import annotations

import re

_MAX_OR_LEXEMES = 32
_LEXEME = re.compile(r"'((?:[^']|'')*)'")


def build_or_tsquery(
    natural_tsquery_text: str, *, max_lexemes: int = _MAX_OR_LEXEMES
) -> tuple[str, int, bool]:
    """Safely quote a capped, first-seen-deduplicated OR tsquery control."""

    if (
        not isinstance(max_lexemes, int)
        or isinstance(max_lexemes, bool)
        or not 1 <= max_lexemes <= _MAX_OR_LEXEMES
    ):
        raise ValueError("max_lexemes must be between 1 and 32")
    unique = tuple(
        dict.fromkeys(
            match.group(1).replace("''", "'") for match in _LEXEME.finditer(natural_tsquery_text)
        )
    )
    selected = unique[:max_lexemes]
    return (
        " | ".join("'" + lexeme.replace("'", "''") + "'" for lexeme in selected),
        len(unique),
        len(unique) > max_lexemes,
    )
