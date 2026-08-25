"""Resumable, bounded execution of the P2 canonical Set B provider evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from legal_chatbot.diagnostics.evaluation.set_b_material_subintent import (
    NORMALIZER_VERSION,
    SetBMaterialSubintentOracle,
    SetBParaphraseCase,
    load_set_b_material_subintent_oracle,
    load_set_b_paraphrases,
    normalize_material_sub_intents,
)
from legal_chatbot.legal_evidence import create_legal_case
from legal_chatbot.legal_evidence.analyzer import (
    LEGAL_QUESTION_ANALYZER_PROMPT_VERSION,
    LEGAL_QUESTION_ANALYZER_SCHEMA_VERSION,
    LEGAL_QUESTION_ANALYZER_VERSION,
    LegalQuestionAnalyzerSettings,
    StrictLegalQuestionAnalysisParser,
    build_legal_question_analyzer_prompt,
    legal_question_analysis_output_format,
)
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.providers.errors import ProviderError
from legal_chatbot.providers.models import (
    GenerationRequest,
    OutputVerbosity,
    ProviderErrorCode,
    ReasoningEffort,
)
from legal_chatbot.providers.port import LLMProviderPort
from legal_chatbot.providers.registry import create_provider

_ARTIFACT_VERSION = "p2-set-b-material-subintent-execution-v3"
_COMPLETE = "COMPLETE"
_PENDING = "PENDING"
_TIMEOUT = "TIMEOUT"
_RATE_LIMIT = "RATE_LIMIT"
_PROVIDER_ERROR = "PROVIDER_ERROR"
_INVALID_OUTPUT = "INVALID_OUTPUT"


@dataclass(frozen=True)
class ExecutionSettings:
    concurrency: int = 3
    request_timeout_seconds: float = 55.0
    hard_case_timeout_seconds: float = 60.0
    retry_limit: int = 2
    retry_backoff_seconds: float = 0.5
    output_token_budget: int = 512

    def validate(self) -> None:
        if not 1 <= self.concurrency <= 10:
            raise ValueError("concurrency must be between 1 and 10")
        if not 1 <= self.request_timeout_seconds <= 60:
            raise ValueError("request timeout must be between 1 and 60 seconds")
        if not self.request_timeout_seconds <= self.hard_case_timeout_seconds <= 75:
            raise ValueError(
                "hard case timeout must be at least request timeout and at most 75 seconds"
            )
        if not 0 <= self.retry_limit <= 3:
            raise ValueError("retry limit must be between 0 and 3")
        if not 0 < self.retry_backoff_seconds <= 5:
            raise ValueError("retry backoff must be between 0 and 5 seconds")
        if not 64 <= self.output_token_budget <= 512:
            raise ValueError("output token budget must be between 64 and 512")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _manifest(
    *,
    oracle: SetBMaterialSubintentOracle,
    evaluation_set_path: Path,
    provider_settings: ProviderSettings,
    execution: ExecutionSettings,
    selected_case_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "oracle_canonical_sha256": oracle.canonical_sha256,
        "evaluation_set_sha256": _sha256(evaluation_set_path),
        "provider": provider_settings.provider,
        "model": provider_settings.model,
        "analyzer_version": LEGAL_QUESTION_ANALYZER_VERSION,
        "prompt_version": LEGAL_QUESTION_ANALYZER_PROMPT_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "structured_output_mode": "json_schema",
        "structured_output_schema_version": LEGAL_QUESTION_ANALYZER_SCHEMA_VERSION,
        "reasoning_effort": ReasoningEffort.MINIMAL.value,
        "verbosity": OutputVerbosity.LOW.value,
        "execution": asdict(execution),
        "selected_case_ids": list(selected_case_ids),
    }


def _case_record(
    case: SetBParaphraseCase, oracle: SetBMaterialSubintentOracle
) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "parent_case_id": case.parent_case_id,
        "status": _PENDING,
        "attempts": 0,
        "generation_duration_ms": None,
        "output_tokens": None,
        "reasoning_tokens": None,
        "visible_output_tokens": None,
        "finish_reason": None,
        "invalid_output_reason": None,
        "normalized_sub_intents": None,
        "parent_gold_set": sorted(oracle.gold_cases[case.parent_case_id].material_sub_intents),
        "exact_set_match": None,
    }


def _new_artifact(
    manifest: dict[str, object],
    paraphrases: tuple[SetBParaphraseCase, ...],
    oracle: SetBMaterialSubintentOracle,
) -> dict[str, object]:
    return {
        "report_schema_version": _ARTIFACT_VERSION,
        "status": "RUNNING",
        "manifest": manifest,
        "cases": [_case_record(case, oracle) for case in paraphrases],
        "generation_metrics": None,
        "measurement": None,
    }


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _load_or_initialize(
    output_path: Path,
    manifest: dict[str, object],
    paraphrases: tuple[SetBParaphraseCase, ...],
    oracle: SetBMaterialSubintentOracle,
    *,
    resume: bool,
) -> dict[str, object]:
    if not output_path.exists() or not resume:
        artifact = _new_artifact(manifest, paraphrases, oracle)
        _atomic_write(output_path, artifact)
        return artifact
    try:
        artifact = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(artifact, dict) or artifact.get("manifest") != manifest:
            raise ValueError
        records = artifact.get("cases")
        if not isinstance(records, list) or len(records) != len(paraphrases):
            raise ValueError
        expected = [(case.case_id, case.parent_case_id) for case in paraphrases]
        actual = [
            (record.get("case_id"), record.get("parent_case_id"))
            for record in records
            if isinstance(record, dict)
        ]
        if actual != expected:
            raise ValueError
        return artifact
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("existing evaluation artifact cannot be safely resumed") from error


def _execution_status(error: BaseException) -> tuple[str, bool, float | None]:
    if isinstance(error, asyncio.TimeoutError):
        return _TIMEOUT, True, None
    if isinstance(error, ProviderError):
        if error.code is ProviderErrorCode.TIMEOUT:
            return _TIMEOUT, error.retryable, error.retry_after_seconds
        if error.code is ProviderErrorCode.RATE_LIMITED:
            return _RATE_LIMIT, error.retryable, error.retry_after_seconds
        return _PROVIDER_ERROR, error.retryable, error.retry_after_seconds
    return _PROVIDER_ERROR, False, None


def _failure_record(
    case: SetBParaphraseCase,
    oracle: SetBMaterialSubintentOracle,
    *,
    status: str,
    attempts: int,
    generation_duration_ms: float | None = None,
    output_tokens: int | None = None,
    invalid_output_reason: str | None = None,
) -> dict[str, object]:
    record = _case_record(case, oracle)
    record.update(
        {
            "status": status,
            "attempts": attempts,
            "generation_duration_ms": generation_duration_ms,
            "output_tokens": output_tokens,
            "invalid_output_reason": invalid_output_reason,
        }
    )
    return record


async def _analyze_case(
    case: SetBParaphraseCase,
    *,
    provider: LLMProviderPort,
    oracle: SetBMaterialSubintentOracle,
    settings: LegalQuestionAnalyzerSettings,
    execution: ExecutionSettings,
) -> dict[str, object]:
    parser = StrictLegalQuestionAnalysisParser()
    prompt = build_legal_question_analyzer_prompt(create_legal_case(case.question), settings)
    started_at = time.perf_counter()
    for attempt in range(1, execution.retry_limit + 2):
        try:
            generated = await asyncio.wait_for(
                provider.generate(
                    GenerationRequest(
                        input_text=prompt,
                        max_output_tokens=settings.max_output_tokens,
                        structured_output=legal_question_analysis_output_format(),
                        reasoning_effort=ReasoningEffort.MINIMAL,
                        verbosity=OutputVerbosity.LOW,
                    )
                ),
                timeout=execution.hard_case_timeout_seconds,
            )
        except Exception as error:
            status, retryable, retry_after = _execution_status(error)
            if not retryable or attempt > execution.retry_limit:
                return _failure_record(
                    case,
                    oracle,
                    status=status,
                    attempts=attempt,
                    generation_duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                )
            delay = (
                retry_after
                if retry_after is not None
                else execution.retry_backoff_seconds * 2 ** (attempt - 1)
            )
            await asyncio.sleep(min(delay, 5.0))
            continue
        try:
            result = parser.parse(generated.text).to_result()
        except ValueError:
            return _failure_record(
                case,
                oracle,
                status=_INVALID_OUTPUT,
                attempts=attempt,
                generation_duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                output_tokens=generated.output_tokens,
                invalid_output_reason=parser.classify_rejection(generated.text),
            )
        normalized = normalize_material_sub_intents(
            tuple(item.description for item in result.sub_intents), oracle
        )
        exact_match = normalized == oracle.gold_cases[case.parent_case_id].material_sub_intents
        return {
            "case_id": case.case_id,
            "parent_case_id": case.parent_case_id,
            "status": _COMPLETE,
            "attempts": attempt,
            "generation_duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "output_tokens": generated.output_tokens,
            "reasoning_tokens": generated.reasoning_tokens,
            "visible_output_tokens": generated.visible_output_tokens,
            "finish_reason": generated.finish_reason,
            "normalized_sub_intents": None if normalized is None else sorted(normalized),
            "parent_gold_set": sorted(oracle.gold_cases[case.parent_case_id].material_sub_intents),
            "exact_set_match": exact_match,
        }
    raise AssertionError("bounded analyzer retry loop must return")


def _percentile(values: list[float | int], percentile: float) -> float:
    index = max(0, min(len(values) - 1, round((len(values) - 1) * percentile)))
    return float(values[index])


def _generation_metrics(records: list[object]) -> dict[str, object]:
    durations = sorted(
        record["generation_duration_ms"]
        for record in records
        if isinstance(record, dict)
        and isinstance(record.get("generation_duration_ms"), (int, float))
    )
    output_tokens = sorted(
        record["output_tokens"]
        for record in records
        if isinstance(record, dict) and isinstance(record.get("output_tokens"), int)
    )
    reasoning_tokens = sorted(
        {
            record["reasoning_tokens"]
            for record in records
            if isinstance(record, dict) and isinstance(record.get("reasoning_tokens"), int)
        }
    )
    visible_output_tokens = sorted(
        {
            record["visible_output_tokens"]
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("visible_output_tokens"), int)
        }
    )
    finish_reasons = sorted(
        {
            record["finish_reason"]
            for record in records
            if isinstance(record, dict) and isinstance(record.get("finish_reason"), str)
        }
    )
    if not durations:
        return {"completed_count": 0, "duration_ms": None, "output_tokens": None}
    return {
        "completed_count": len(durations),
        "duration_ms": {
            "p50": _percentile(durations, 0.50),
            "p95": _percentile(durations, 0.95),
            "max": float(durations[-1]),
        },
        "output_tokens": (
            None
            if not output_tokens
            else {
                "p50": _percentile(output_tokens, 0.50),
                "p95": _percentile(output_tokens, 0.95),
                "max": int(output_tokens[-1]),
            }
        ),
        "reasoning_tokens": reasoning_tokens,
        "visible_output_tokens": visible_output_tokens,
        "finish_reasons": finish_reasons,
    }


def _measurement(
    artifact: dict[str, object], oracle: SetBMaterialSubintentOracle
) -> dict[str, object] | None:
    records = artifact["cases"]
    assert isinstance(records, list)
    if len(records) != oracle.expected_paraphrases:
        return None
    if any(not isinstance(record, dict) or record.get("status") != _COMPLETE for record in records):
        return None
    exact_matches = [record["exact_set_match"] for record in records]
    if any(not isinstance(value, bool) for value in exact_matches):
        raise ValueError("completed artifact has invalid semantic measurement")
    matched = sum(exact_matches)
    measured = len(records)
    return {
        "measured": measured,
        "matched": matched,
        "agreement": matched / measured,
        "minimum_measured_paraphrases": oracle.minimum_measured_paraphrases,
        "threshold": oracle.threshold,
        "passed": (
            measured >= oracle.minimum_measured_paraphrases
            and matched / measured >= oracle.threshold
        ),
    }


async def execute(
    *,
    output_path: Path,
    oracle: SetBMaterialSubintentOracle,
    paraphrases: tuple[SetBParaphraseCase, ...],
    evaluation_set_path: Path,
    provider: LLMProviderPort,
    provider_settings: ProviderSettings,
    execution: ExecutionSettings,
    resume: bool,
) -> dict[str, object]:
    """Run or safely resume bounded cases and atomically persist each completed result."""

    execution.validate()
    manifest = _manifest(
        oracle=oracle,
        evaluation_set_path=evaluation_set_path,
        provider_settings=provider_settings,
        execution=execution,
        selected_case_ids=tuple(case.case_id for case in paraphrases),
    )
    artifact = _load_or_initialize(output_path, manifest, paraphrases, oracle, resume=resume)
    records = artifact["cases"]
    assert isinstance(records, list)
    pending = tuple(
        case
        for case, record in zip(paraphrases, records, strict=True)
        if record["status"] != _COMPLETE
    )
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(execution.concurrency)
    analyzer_settings = LegalQuestionAnalyzerSettings(
        enabled=True,
        timeout_seconds=min(execution.hard_case_timeout_seconds, 30.0),
        max_output_tokens=execution.output_token_budget,
    )

    async def run_case(case: SetBParaphraseCase) -> None:
        async with semaphore:
            record = await _analyze_case(
                case,
                provider=provider,
                oracle=oracle,
                settings=analyzer_settings,
                execution=execution,
            )
        async with lock:
            index = next(
                index for index, current in enumerate(records) if current["case_id"] == case.case_id
            )
            records[index] = record
            artifact["status"] = "RUNNING"
            artifact["generation_metrics"] = _generation_metrics(records)
            artifact["measurement"] = None
            _atomic_write(output_path, artifact)

    await asyncio.gather(*(run_case(case) for case in pending))
    artifact["generation_metrics"] = _generation_metrics(records)
    artifact["measurement"] = _measurement(artifact, oracle)
    if any(record["status"] != _COMPLETE for record in records):
        artifact["status"] = "BLOCKED_PROVIDER_EXECUTION"
    elif artifact["measurement"] is None:
        artifact["status"] = "SAMPLE_COMPLETE"
    else:
        artifact["status"] = "COMPLETE"
    _atomic_write(output_path, artifact)
    return artifact


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--set-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=55.0)
    parser.add_argument("--hard-case-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retry-limit", type=int, default=2)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.5)
    parser.add_argument("--output-token-budget", type=int, default=512)
    parser.add_argument("--case-ids", default=None)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    oracle = load_set_b_material_subintent_oracle(arguments.oracle)
    all_paraphrases = load_set_b_paraphrases(arguments.set_b, oracle)
    selected_case_ids = (
        None
        if arguments.case_ids is None
        else tuple(
            value.strip().upper() for value in arguments.case_ids.split(",") if value.strip()
        )
    )
    paraphrases = (
        all_paraphrases
        if selected_case_ids is None
        else tuple(case for case in all_paraphrases if case.case_id in selected_case_ids)
    )
    if not paraphrases or (
        selected_case_ids is not None and len(paraphrases) != len(selected_case_ids)
    ):
        raise ValueError("selected case identifiers are invalid")
    execution = ExecutionSettings(
        concurrency=arguments.concurrency,
        request_timeout_seconds=arguments.request_timeout_seconds,
        hard_case_timeout_seconds=arguments.hard_case_timeout_seconds,
        retry_limit=arguments.retry_limit,
        retry_backoff_seconds=arguments.retry_backoff_seconds,
        output_token_budget=arguments.output_token_budget,
    )
    execution.validate()
    provider_settings = ProviderSettings().model_copy(
        update={"response_timeout_seconds": execution.request_timeout_seconds}
    )
    provider = create_provider(provider_settings)
    try:
        return await execute(
            output_path=arguments.output,
            oracle=oracle,
            paraphrases=paraphrases,
            evaluation_set_path=arguments.set_b,
            provider=provider,
            provider_settings=provider_settings,
            execution=execution,
            resume=not arguments.no_resume,
        )
    finally:
        await provider.aclose()


def main() -> int:
    result = asyncio.run(_run(_arguments()))
    return 0 if result["status"] in {"COMPLETE", "SAMPLE_COMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
