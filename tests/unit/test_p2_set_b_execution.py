import importlib.util
import json
import sys
from pathlib import Path

import pytest

from legal_chatbot.diagnostics.evaluation.set_b_material_subintent import (
    load_set_b_material_subintent_oracle,
    load_set_b_paraphrases,
)
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import GenerationRequest, GenerationResult, ProviderErrorCode


def _runner_module():
    spec = importlib.util.spec_from_file_location(
        "p2_set_b_runner", Path("scripts/evaluate_p2_set_b_analyzer.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _ProviderSettings:
    provider = "shineshop"
    model = "evaluation-test-model"


class _Provider:
    def __init__(self, output: str, *, first_error: Exception | None = None) -> None:
        self._output = output
        self._first_error = first_error
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        if self.calls == 1 and self._first_error is not None:
            raise self._first_error
        return GenerationResult(
            text=self._output,
            provider="stub",
            model="stub",
            duration_ms=1,
            output_tokens=12,
        )

    async def health_check(self):
        raise AssertionError("health is outside execution runner tests")

    async def aclose(self) -> None:
        return None


def _valid_output() -> str:
    return json.dumps(
        {
            "main_intent": "procedure",
            "legal_actor": None,
            "legal_action_event": None,
            "explicit_time": [],
            "legal_topics": [],
            "ambiguity": False,
            "sub_intents": [
                {
                    "description": "điều kiện học vượt",
                    "retrieval_concepts": [],
                    "preferred_source_tiers": [],
                }
            ],
            "preferred_source_tiers": [],
            "retrieval_concepts": [],
        }
    )


def _inputs():
    oracle = load_set_b_material_subintent_oracle(
        Path("docs/evals/oracle/set-b-material-subintent-oracle-v1.0.0.json")
    )
    paraphrases = load_set_b_paraphrases(Path("docs/evals/m2_evaluation_set.json"), oracle)
    return oracle, paraphrases


@pytest.mark.asyncio
async def test_execution_retries_rate_limit_and_persists_completed_cases_atomically(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    oracle, paraphrases = _inputs()
    provider = _Provider(
        _valid_output(),
        first_error=ProviderError(ProviderErrorCode.RATE_LIMITED, retryable=True),
    )
    output = tmp_path / "measurement.json"

    artifact = await runner.execute(
        output_path=output,
        oracle=oracle,
        paraphrases=paraphrases,
        evaluation_set_path=Path("docs/evals/m2_evaluation_set.json"),
        provider=provider,
        provider_settings=_ProviderSettings(),
        execution=runner.ExecutionSettings(
            concurrency=3, retry_limit=1, retry_backoff_seconds=0.01
        ),
        resume=True,
    )

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["status"] == "COMPLETE"
    assert persisted["manifest"] == artifact["manifest"]
    assert len(persisted["cases"]) == 30
    assert all(item["status"] == "COMPLETE" for item in persisted["cases"])
    assert any(item["attempts"] == 2 for item in persisted["cases"])
    assert persisted["measurement"]["measured"] == 30
    assert persisted["generation_metrics"]["output_tokens"]["max"] == 12


@pytest.mark.asyncio
async def test_sample_execution_is_complete_without_claiming_full_set_measurement(
    tmp_path: Path,
) -> None:
    runner = _runner_module()
    oracle, paraphrases = _inputs()

    artifact = await runner.execute(
        output_path=tmp_path / "sample.json",
        oracle=oracle,
        paraphrases=paraphrases[:1],
        evaluation_set_path=Path("docs/evals/m2_evaluation_set.json"),
        provider=_Provider(_valid_output()),
        provider_settings=_ProviderSettings(),
        execution=runner.ExecutionSettings(concurrency=1, retry_limit=0),
        resume=False,
    )

    assert artifact["status"] == "SAMPLE_COMPLETE"
    assert artifact["measurement"] is None
    assert artifact["generation_metrics"]["completed_count"] == 1


@pytest.mark.asyncio
async def test_execution_failures_do_not_become_semantic_mismatches(tmp_path: Path) -> None:
    runner = _runner_module()
    oracle, paraphrases = _inputs()
    output = tmp_path / "measurement.json"

    artifact = await runner.execute(
        output_path=output,
        oracle=oracle,
        paraphrases=paraphrases,
        evaluation_set_path=Path("docs/evals/m2_evaluation_set.json"),
        provider=_Provider("not-json"),
        provider_settings=_ProviderSettings(),
        execution=runner.ExecutionSettings(concurrency=3, retry_limit=0),
        resume=False,
    )

    assert artifact["status"] == "BLOCKED_PROVIDER_EXECUTION"
    assert artifact["measurement"] is None
    assert {item["status"] for item in artifact["cases"]} == {"INVALID_OUTPUT"}
    assert all(item["exact_set_match"] is None for item in artifact["cases"])
    assert {item["invalid_output_reason"] for item in artifact["cases"]} == {"JSON_SYNTAX"}


def test_execution_status_distinguishes_timeout_rate_limit_and_provider_error() -> None:
    runner = _runner_module()

    assert runner._execution_status(TimeoutError())[0] == "TIMEOUT"
    assert (
        runner._execution_status(ProviderError(ProviderErrorCode.RATE_LIMITED, retryable=True))[0]
        == "RATE_LIMIT"
    )
    assert (
        runner._execution_status(ProviderError(ProviderErrorCode.UNAVAILABLE, retryable=True))[0]
        == "PROVIDER_ERROR"
    )


@pytest.mark.asyncio
async def test_resume_rejects_changed_model_manifest(tmp_path: Path) -> None:
    runner = _runner_module()
    oracle, paraphrases = _inputs()
    output = tmp_path / "measurement.json"
    provider = _Provider(_valid_output())

    await runner.execute(
        output_path=output,
        oracle=oracle,
        paraphrases=paraphrases,
        evaluation_set_path=Path("docs/evals/m2_evaluation_set.json"),
        provider=provider,
        provider_settings=_ProviderSettings(),
        execution=runner.ExecutionSettings(concurrency=3, retry_limit=0),
        resume=True,
    )
    changed = _ProviderSettings()
    changed.model = "different-evaluation-model"
    with pytest.raises(ValueError, match="cannot be safely resumed"):
        await runner.execute(
            output_path=output,
            oracle=oracle,
            paraphrases=paraphrases,
            evaluation_set_path=Path("docs/evals/m2_evaluation_set.json"),
            provider=provider,
            provider_settings=changed,
            execution=runner.ExecutionSettings(concurrency=3, retry_limit=0),
            resume=True,
        )
