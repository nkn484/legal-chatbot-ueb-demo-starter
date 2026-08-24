"""Strict, synchronous parsing of provider JSON output without provider dependencies."""

import json
from typing import Any
from unicodedata import normalize

from legal_chatbot.chat.errors import ChatError, ChatErrorCode, ProviderOutputFailureClass
from legal_chatbot.chat.models import (
    ANSWER_MAX_CHARS,
    ProviderAnswer,
    classify_provider_answer_safety,
)
from legal_chatbot.chat.port import ProviderOutputParserPort


class _DuplicateJsonKeyError(ValueError):
    """Internal marker for duplicate JSON keys rejected by the strict parser."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object only when every JSON key appears once."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


class StrictProviderJsonParser(ProviderOutputParserPort):
    """Accept only one JSON object containing exactly one safe answer string."""

    def parse(self, output: str) -> ProviderAnswer:
        """Parse provider output and normalize every invalid value to a safe chat error."""

        try:
            if not isinstance(output, str):
                raise ChatError(
                    ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                    ProviderOutputFailureClass.JSON_SYNTAX,
                )
            parsed = json.loads(output, object_pairs_hook=_reject_duplicate_keys)
        except _DuplicateJsonKeyError:
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.ROOT_OR_KEYSET,
            ) from None
        except json.JSONDecodeError:
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.JSON_SYNTAX,
            ) from None
        except Exception:
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.JSON_SYNTAX,
            ) from None

        if not isinstance(parsed, dict) or set(parsed) != {"answer"}:
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.ROOT_OR_KEYSET,
            )
        answer = parsed["answer"]
        if not isinstance(answer, str):
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.ANSWER_TYPE,
            )
        normalized_answer = normalize("NFC", answer).strip()
        if not normalized_answer or len(normalized_answer) > ANSWER_MAX_CHARS:
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.ANSWER_EMPTY_OR_BOUND,
            )
        safety_class = classify_provider_answer_safety(normalized_answer)
        if safety_class is not None:
            raise ChatError(ChatErrorCode.INVALID_PROVIDER_OUTPUT, safety_class)
        try:
            return ProviderAnswer(answer=answer)
        except Exception:
            # Preserve the legacy catch-all for any future ProviderAnswer safety
            # validator that is not represented by the authoritative classifier.
            raise ChatError(
                ChatErrorCode.INVALID_PROVIDER_OUTPUT,
                ProviderOutputFailureClass.ANSWER_UNSAFE_METADATA,
            ) from None
