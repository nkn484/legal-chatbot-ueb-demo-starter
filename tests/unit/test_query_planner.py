"""Focused fail-soft and strict-contract coverage for the M08.1 query planner."""

import asyncio
import json

import pytest

from legal_chatbot.chat import ChatSettings, LLMQueryPlanner, QueryPlannerOutcome
from legal_chatbot.chat.planner_parser import StrictQueryPlannerParser
from legal_chatbot.chat.planner_prompt import build_query_planner_prompt
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.models import GenerationRequest, GenerationResult


def _provider_settings(**overrides: object) -> ProviderSettings:
    values: dict[str, object] = {
        "LLM_BASE_URL": "https://api.example.test/v1",
        "LLM_MODEL": "demo-model",
        "LLM_API_KEY": "test-key",
    }
    values.update(overrides)
    return ProviderSettings.model_validate(values)


@pytest.mark.parametrize(
    "output",
    (
        '{"anchor_mentions":[],"key_phrases":[],"expansion_terms":[],"extra":[]}',
        '{"anchor_mentions":[],"anchor_mentions":[],"key_phrases":[],"expansion_terms":[]}',
        '```json\n{"anchor_mentions":[],"key_phrases":[],"expansion_terms":[]}\n```',
        '{"anchor_mentions":[],"key_phrases":["https://bad.test"],"expansion_terms":[]}',
        '{"anchor_mentions":[],"key_phrases":["select * from documents"],"expansion_terms":[]}',
        '{"anchor_mentions":[],"key_phrases":["nghiên cứu \\"or\\""],"expansion_terms":[]}',
        '{"anchor_mentions":[],"key_phrases":["Đây là câu trả lời"],"expansion_terms":[]}',
        '{"anchor_mentions":[],"key_phrases":["nghiên cứu\\nchuyên môn"],"expansion_terms":[]}',
        '{"anchor_mentions":["Luật không có trong câu hỏi"],"key_phrases":[],"expansion_terms":[]}',
        '{"anchor_mentions":[],"key_phrases":["Điều 3"],"expansion_terms":[]}',
    ),
)
def test_strict_planner_parser_rejects_malformed_unsafe_and_drifting_output(output: str) -> None:
    with pytest.raises(ValueError):
        StrictQueryPlannerParser().parse(
            output,
            "Luật Giáo dục đại học yêu cầu tiêu chuẩn nghiên cứu như thế nào?",
            max_phrases=2,
            max_expansion_terms=4,
        )


def test_strict_planner_parser_normalizes_and_preserves_input_anchor() -> None:
    plan = StrictQueryPlannerParser().parse(
        """{
        "anchor_mentions":["Luật   Giáo dục đại học"],
        "key_phrases":["tiêu chuẩn nghiên cứu"],
        "expansion_terms":["hoạt động khoa học"]
        }""",
        "Luật Giáo dục đại học yêu cầu tiêu chuẩn nghiên cứu như thế nào?",
        max_phrases=2,
        max_expansion_terms=4,
    )

    assert plan.anchor_mentions == ("Luật Giáo dục đại học",)
    assert plan.key_phrases == ("tiêu chuẩn nghiên cứu",)


def test_anchor_containment_normalizes_whitespace_and_casefolds() -> None:
    plan = StrictQueryPlannerParser().parse(
        '{"anchor_mentions":["luật giáo dục đại học"],"key_phrases":[],"expansion_terms":[]}',
        "LUẬT   Giáo dục đại học yêu cầu tiêu chuẩn nghiên cứu như thế nào?",
        max_phrases=2,
        max_expansion_terms=4,
    )

    assert plan.anchor_mentions == ("luật giáo dục đại học",)


@pytest.mark.parametrize(
    "created_identity",
    (
        "Công văn số 123",
        "số 123",
        "Sở Giáo dục và Đào tạo",
        "Cục Pháp chế",
        "Tổng cục Thuế",
        "Hội đồng trường",
    ),
)
def test_strict_planner_parser_rejects_created_vietnamese_legal_identities(
    created_identity: str,
) -> None:
    output = json.dumps(
        {"anchor_mentions": [], "key_phrases": [created_identity], "expansion_terms": []},
        ensure_ascii=False,
    )

    with pytest.raises(ValueError):
        StrictQueryPlannerParser().parse(
            output,
            "Tiêu chuẩn nghiên cứu khoa học là gì?",
            max_phrases=2,
            max_expansion_terms=4,
        )


@pytest.mark.parametrize(
    "input_identity",
    (
        "Công văn số 123",
        "số 123",
        "Sở Giáo dục và Đào tạo",
        "Cục Pháp chế",
        "Tổng cục Thuế",
        "Hội đồng trường",
    ),
)
def test_strict_planner_parser_allows_protected_identities_literal_in_input(
    input_identity: str,
) -> None:
    output = json.dumps(
        {"anchor_mentions": [], "key_phrases": [input_identity], "expansion_terms": []},
        ensure_ascii=False,
    )

    plan = StrictQueryPlannerParser().parse(
        output,
        f"Quy định về {input_identity}",
        max_phrases=2,
        max_expansion_terms=4,
    )

    assert plan.key_phrases == (input_identity,)


def test_planner_prompt_forbids_protected_legal_identity_drift() -> None:
    prompt = build_query_planner_prompt("Câu hỏi hiện tại")

    for protected_identity in (
        "document titles or numbers",
        "Điều/Khoản/Điểm",
        "agencies",
        "time",
        "legal status",
    ):
        assert protected_identity in prompt


class _FakeProvider:
    def __init__(self, result: GenerationResult | Exception, *, pause: float = 0) -> None:
        self.result = result
        self.pause = pause
        self.calls: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls.append(request)
        if self.pause:
            await asyncio.sleep(self.pause)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _generation(text: str) -> GenerationResult:
    return GenerationResult(
        text=text,
        provider="fake-provider",
        model="fake-model",
        duration_ms=0,
    )


class _ParserProbe:
    def __init__(self) -> None:
        self.calls = 0

    def parse(self, output: str, **kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("oversize output must not be parsed")


@pytest.mark.asyncio
async def test_llm_planner_makes_one_local_timeout_bound_call_and_never_retries() -> None:
    provider = _FakeProvider(
        _generation('{"anchor_mentions":[],"key_phrases":["nghiên cứu"],"expansion_terms":[]}'),
        pause=0.02,
    )
    planner = LLMQueryPlanner(
        provider,  # type: ignore[arg-type]
        ChatSettings(retrieval_planner_timeout_seconds=0.01),
        _provider_settings(),
    )

    result = await planner.plan("Tiêu chuẩn nghiên cứu là gì?")

    assert result.outcome is QueryPlannerOutcome.PROVIDER_FAILURE
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_llm_planner_sends_only_the_current_question_and_returns_valid_plan() -> None:
    provider = _FakeProvider(
        _generation(
            '{"anchor_mentions":[],"key_phrases":["tiêu chuẩn nghiên cứu"],'
            '"expansion_terms":["hoạt động khoa học"]}'
        )
    )
    planner = LLMQueryPlanner(provider, ChatSettings(), _provider_settings())  # type: ignore[arg-type]

    result = await planner.plan("Tiêu chuẩn nghiên cứu là gì?")

    assert result.outcome is QueryPlannerOutcome.PLANNED
    assert result.plan is not None
    assert len(provider.calls) == 1
    assert "Tiêu chuẩn nghiên cứu là gì?" in provider.calls[0].input_text
    assert provider.calls[0].max_output_tokens == 96


@pytest.mark.asyncio
async def test_llm_planner_accepts_output_at_fixed_response_byte_cap() -> None:
    valid_plan = '{"anchor_mentions":[],"key_phrases":["nghiên cứu"],"expansion_terms":[]}'
    output = valid_plan + " " * (4_096 - len(valid_plan.encode("utf-8")))
    planner = LLMQueryPlanner(
        _FakeProvider(_generation(output)),  # type: ignore[arg-type]
        ChatSettings(),
        _provider_settings(),
    )

    result = await planner.plan("Tiêu chuẩn nghiên cứu là gì?")

    assert result.outcome is QueryPlannerOutcome.PLANNED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output_bytes", "provider_settings"),
    (
        (4_097, _provider_settings()),
        (1_025, _provider_settings(LLM_MAX_RESPONSE_BYTES=1_024)),
    ),
)
async def test_llm_planner_rejects_oversize_output_before_parsing(
    output_bytes: int, provider_settings: ProviderSettings
) -> None:
    parser = _ParserProbe()
    planner = LLMQueryPlanner(
        _FakeProvider(_generation("x" * output_bytes)),  # type: ignore[arg-type]
        ChatSettings(),
        provider_settings,
        parser=parser,  # type: ignore[arg-type]
    )

    result = await planner.plan("Tiêu chuẩn nghiên cứu là gì?")

    assert result.outcome is QueryPlannerOutcome.INVALID_OUTPUT
    assert parser.calls == 0
