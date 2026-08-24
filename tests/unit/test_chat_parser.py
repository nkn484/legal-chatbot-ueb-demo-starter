"""Focused strict provider-output parsing coverage for M06 Phase 3."""

import pytest

from legal_chatbot.chat.errors import ChatError, ChatErrorCode, ProviderOutputFailureClass
from legal_chatbot.chat.parser import StrictProviderJsonParser


def test_parser_accepts_exactly_one_safe_answer_object() -> None:
    answer = StrictProviderJsonParser().parse('{"answer":"  A grounded answer.  "}')

    assert answer.answer == "A grounded answer."


@pytest.mark.parametrize(
    ("output", "expected_answer"),
    [
        (
            '{"answer":"First paragraph.\\nSecond paragraph."}',
            "First paragraph.\nSecond paragraph.",
        ),
        (
            '{"answer":"First paragraph.\\r\\nSecond paragraph."}',
            "First paragraph.\r\nSecond paragraph.",
        ),
        ('{"answer":"Term\\tDefinition"}', "Term\tDefinition"),
    ],
)
def test_parser_accepts_and_preserves_ordinary_formatting_controls(
    output: str, expected_answer: str
) -> None:
    assert StrictProviderJsonParser().parse(output).answer == expected_answer


@pytest.mark.parametrize(
    ("output", "failure_class"),
    [
        (1, ProviderOutputFailureClass.JSON_SYNTAX),
        ('```json\n{"answer":"answer"}\n```', ProviderOutputFailureClass.JSON_SYNTAX),
        ('{"answer":"answer"} trailing', ProviderOutputFailureClass.JSON_SYNTAX),
        ("{", ProviderOutputFailureClass.JSON_SYNTAX),
        ('{"answer":"one","answer":"two"}', ProviderOutputFailureClass.ROOT_OR_KEYSET),
        ("[]", ProviderOutputFailureClass.ROOT_OR_KEYSET),
        ("{}", ProviderOutputFailureClass.ROOT_OR_KEYSET),
        ('{"other":"answer"}', ProviderOutputFailureClass.ROOT_OR_KEYSET),
        ('{"answer":"answer","extra":"value"}', ProviderOutputFailureClass.ROOT_OR_KEYSET),
        ('{"answer":1}', ProviderOutputFailureClass.ANSWER_TYPE),
        ('{"answer":"   "}', ProviderOutputFailureClass.ANSWER_EMPTY_OR_BOUND),
        ('{"answer":"' + "x" * 4_001 + '"}', ProviderOutputFailureClass.ANSWER_EMPTY_OR_BOUND),
        ('{"answer":"bad\\u0001control"}', ProviderOutputFailureClass.ANSWER_CONTROL),
        ('{"answer":"bad\\u0000control"}', ProviderOutputFailureClass.ANSWER_CONTROL),
        ('{"answer":"bad\\u001bcontrol"}', ProviderOutputFailureClass.ANSWER_CONTROL),
        ('{"answer":"bad\\u202econtrol"}', ProviderOutputFailureClass.ANSWER_CONTROL),
        (
            '{"answer":"safe\\nformatting\\tand\\u0000unsafe"}',
            ProviderOutputFailureClass.ANSWER_CONTROL,
        ),
        ('{"answer":"https://example.test"}', ProviderOutputFailureClass.ANSWER_URL),
        (
            '{"answer":"00000000-0000-0000-0000-000000000001"}',
            ProviderOutputFailureClass.ANSWER_UUID,
        ),
        ('{"answer":"[E1]"}', ProviderOutputFailureClass.ANSWER_EVIDENCE_TOKEN),
        ('{"answer":"See E12."}', ProviderOutputFailureClass.ANSWER_EVIDENCE_TOKEN),
        ('{"answer":"citation_id"}', ProviderOutputFailureClass.ANSWER_CITATION_ID),
    ],
)
def test_parser_classifies_every_invalid_output_without_exposing_it(
    output: object, failure_class: ProviderOutputFailureClass
) -> None:
    with pytest.raises(ChatError) as error:
        StrictProviderJsonParser().parse(output)  # type: ignore[arg-type]

    assert error.value.code is ChatErrorCode.INVALID_PROVIDER_OUTPUT
    assert error.value.provider_output_class is failure_class
    assert str(error.value) == ChatErrorCode.INVALID_PROVIDER_OUTPUT


def test_parser_uses_documented_safety_precedence() -> None:
    output = (
        '{"answer":"\\u0001https://example.test '
        '00000000-0000-0000-0000-000000000001 [E1] citation_id"}'
    )

    with pytest.raises(ChatError) as error:
        StrictProviderJsonParser().parse(output)

    assert error.value.provider_output_class is ProviderOutputFailureClass.ANSWER_CONTROL


def test_parser_never_echoes_untrusted_output_in_errors() -> None:
    sentinel = "SENTINEL_DO_NOT_ECHO https:unsafe"

    with pytest.raises(ChatError) as error:
        StrictProviderJsonParser().parse(f'{{"answer":"{sentinel}"}}')

    assert sentinel not in str(error.value)
