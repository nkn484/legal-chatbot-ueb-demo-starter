"""Strict, dependency-free loading of the local M00 credential file.

The loader is intentionally narrow: it recognizes only the M00 credential
allowlist, never logs values, and returns names/status rather than secrets.
"""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unicodedata import category


MAX_DOTENV_BYTES = 64 * 1024
ALLOWED_ENV_KEYS = frozenset({"SHINE_API_KEY", "VBQPPL_TLS_VERIFY", "ZALO_BOT_SECRET_TOKEN", "ZALO_BOT_TOKEN", "ZALO_BOT_WEBHOOK_URL"})
_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class EnvLoadStatus:
    """Safe result of a local dotenv load; secret values are never retained."""

    status: Literal["MISSING", "LOADED", "REJECTED", "UNREADABLE"]
    loaded_keys: frozenset[str]


def repo_env_path() -> Path:
    """Return the fixed repository-root dotenv location."""

    return Path(__file__).resolve().parents[2] / ".env"


def _starts_allowed_key(line: str) -> bool:
    """Recognize malformed attempts to configure an allowed key."""

    candidate = line.lstrip()
    if candidate.startswith("export"):
        candidate = candidate[6:].lstrip()
    return any(
        candidate.startswith(key)
        and (len(candidate) == len(key) or candidate[len(key)] in "= \t")
        for key in ALLOWED_ENV_KEYS
    )


def _parse_value(value: str) -> str | None:
    """Parse one literal value, rejecting shell-like dotenv extensions."""

    if any(character in value for character in ("\\", "$", "`")) or any(category(character) == "Cc" for character in value):
        return None
    if value.startswith(("'", '"')):
        quote = value[0]
        if len(value) < 2 or not value.endswith(quote):
            return None
        inner = value[1:-1]
        if quote in inner:
            return None
        return inner
    if "'" in value or '"' in value or any(character.isspace() for character in value):
        return None
    return value


def _parse_allowed_values(text: str) -> dict[str, str] | None:
    """Return parsed allowed values, or reject the complete file atomically."""

    parsed: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            if _starts_allowed_key(line):
                return None
            continue
        key, value = line.split("=", 1)
        if key not in ALLOWED_ENV_KEYS:
            if _starts_allowed_key(line):
                return None
            continue
        if not _KEY.fullmatch(key) or key in parsed:
            return None
        parsed_value = _parse_value(value)
        if parsed_value is None:
            return None
        parsed[key] = parsed_value
    return parsed


def load_repo_env(
    path: Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> EnvLoadStatus:
    """Load allowed local credentials without exposing or overriding secrets.

    An invalid or unreadable file leaves ``environ`` untouched.  ``path`` is an
    injectable test seam; production callers use the repository-root ``.env``.
    """

    dotenv_path = path or repo_env_path()
    try:
        raw = dotenv_path.read_bytes()
    except FileNotFoundError:
        return EnvLoadStatus("MISSING", frozenset())
    except OSError:
        return EnvLoadStatus("UNREADABLE", frozenset())
    if len(raw) > MAX_DOTENV_BYTES:
        return EnvLoadStatus("REJECTED", frozenset())
    try:
        parsed = _parse_allowed_values(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return EnvLoadStatus("REJECTED", frozenset())
    if parsed is None:
        return EnvLoadStatus("REJECTED", frozenset())

    target = os.environ if environ is None else environ
    loaded: set[str] = set()
    for key, value in parsed.items():
        if target.get(key):
            continue
        target[key] = value
        loaded.add(key)
    return EnvLoadStatus("LOADED", frozenset(loaded))
