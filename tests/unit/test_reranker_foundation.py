"""Unit contracts for the isolated pinned reranker foundation and prefetch lane."""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from legal_chatbot.reranking import prefetch
from legal_chatbot.reranking.config import RerankerSettings
from legal_chatbot.reranking.constants import (
    ONNX_MODEL_FILE,
    REQUIRED_MODEL_FILES,
    RERANKER_LICENSE,
    RERANKER_MODEL_ID,
    RERANKER_MODEL_REVISION,
)
from legal_chatbot.reranking.errors import RerankerError, RerankerErrorCode
from legal_chatbot.reranking.fastembed_adapter import FastEmbedRerankerAdapter
from legal_chatbot.reranking.models import (
    RerankCandidate,
    RerankerProfile,
    RerankRequest,
    RerankResult,
)


def _request() -> RerankRequest:
    return RerankRequest(
        query="question",
        candidates=(
            RerankCandidate(chunk_id="opaque-a", text="first evidence"),
            RerankCandidate(chunk_id="opaque-b", text="second evidence"),
        ),
    )


def test_reranker_profile_contract_and_settings_bounds() -> None:
    assert RerankerProfile().model_id == RERANKER_MODEL_ID
    assert RerankerProfile().revision == RERANKER_MODEL_REVISION
    assert RerankerProfile().model_file == ONNX_MODEL_FILE
    assert RerankerProfile().license == RERANKER_LICENSE
    settings = RerankerSettings(_env_file=None)
    assert (settings.batch_size, settings.threads, settings.candidate_max) == (8, 2, 8)
    assert (settings.query_max_chars, settings.hydrated_text_max_chars) == (4_000, 2_000)
    assert settings.timeout_seconds == 5.0
    with pytest.raises(ValidationError):
        RerankerSettings(_env_file=None, candidate_max=9)
    with pytest.raises(ValidationError):
        RerankRequest(query="q" * 4_001, candidates=(_request().candidates[0],))
    with pytest.raises(ValidationError, match="candidate chunk IDs must be unique"):
        RerankRequest(
            query="question",
            candidates=(
                RerankCandidate(chunk_id="same", text="one"),
                RerankCandidate(chunk_id="same", text="two"),
            ),
        )


def test_reranker_timeout_setting_reads_env_and_enforces_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RERANKER_TIMEOUT_SECONDS", "12.5")
    assert RerankerSettings(_env_file=None).timeout_seconds == 12.5
    for timeout in (0.99, 30.01):
        with pytest.raises(ValidationError):
            RerankerSettings(_env_file=None, timeout_seconds=timeout)


def test_reranker_result_requires_one_finite_logit_per_unique_input_id() -> None:
    request = _request()
    result = RerankResult.from_request(request, (9.5, -12.0))
    assert result.candidate_ids == ("opaque-a", "opaque-b")
    assert result.scores == (9.5, -12.0)
    with pytest.raises(ValidationError, match="align exactly"):
        RerankResult(candidate_ids=("opaque-a", "opaque-b"), scores=(1.0,))
    with pytest.raises(ValidationError, match="finite"):
        RerankResult(candidate_ids=("opaque-a",), scores=(float("nan"),))
    with pytest.raises(ValidationError, match="unique"):
        RerankResult(candidate_ids=("opaque-a", "opaque-a"), scores=(1.0, 2.0))


@pytest.mark.asyncio
async def test_reranker_adapter_is_lazy_and_does_not_retain_query_or_text() -> None:
    calls = 0
    received: list[tuple[str, tuple[str, ...], int]] = []

    class FakeModel:
        def rerank(
            self, query: str, texts: tuple[str, ...], *, batch_size: int
        ) -> tuple[float, ...]:
            received.append((query, texts, batch_size))
            return (3.5, -2.25)

    def factory(settings: RerankerSettings) -> FakeModel:
        nonlocal calls
        calls += 1
        assert settings.threads == 2
        return FakeModel()

    adapter = FastEmbedRerankerAdapter(RerankerSettings(), model_factory=factory)
    assert calls == 0
    result = await adapter.rerank(_request())
    assert result.scores == (3.5, -2.25)
    assert calls == 1
    assert received == [("question", ("first evidence", "second evidence"), 8)]
    assert not any(
        needle in repr(value)
        for needle in ("question", "first evidence", "second evidence")
        for value in adapter.__dict__.values()
    )


@pytest.mark.asyncio
async def test_reranker_fastembed_registration_load_and_rerank_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import legal_chatbot.reranking.fastembed_adapter as adapter_module

    registered: list[dict[str, object]] = []
    constructed: list[dict[str, object]] = []

    class ModelSource:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class TextCrossEncoder:
        @staticmethod
        def add_custom_model(**kwargs: object) -> None:
            registered.append(kwargs)

        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)

        def rerank(
            self, query: str, texts: tuple[str, ...], *, batch_size: int
        ) -> tuple[float, ...]:
            assert query == "question"
            assert texts == ("first evidence", "second evidence")
            assert batch_size == 8
            return (1.0, -1.0)

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace()
    )
    monkeypatch.setitem(
        sys.modules,
        "fastembed.rerank.cross_encoder",
        types.SimpleNamespace(TextCrossEncoder=TextCrossEncoder),
    )
    monkeypatch.setitem(
        sys.modules,
        "fastembed.common.model_description",
        types.SimpleNamespace(ModelSource=ModelSource),
    )
    monkeypatch.setattr(adapter_module, "_custom_model_registered", False)
    validated_paths: list[Path] = []
    monkeypatch.setattr(adapter_module, "validate_model_artifact", validated_paths.append)

    adapter = FastEmbedRerankerAdapter(RerankerSettings())
    await adapter.rerank(_request())
    await adapter.rerank(_request())
    assert len(registered) == 1
    assert registered[0]["sources"].kwargs == {"hf": RERANKER_MODEL_ID}  # type: ignore[index,union-attr]
    assert registered[0]["model_file"] == ONNX_MODEL_FILE
    assert registered[0]["license"] == RERANKER_LICENSE
    assert validated_paths == [Path("/models/mmarco-minilm-l12-h384-int8-avx2")]
    assert constructed[0]["specific_model_path"] == "/models/mmarco-minilm-l12-h384-int8-avx2"
    assert constructed[0]["local_files_only"] is True
    assert constructed[0]["providers"] == ["CPUExecutionProvider"]
    assert constructed[0]["threads"] == 2


def test_reranker_duplicate_global_registration_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    import legal_chatbot.reranking.fastembed_adapter as adapter_module

    class ModelSource:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class TextCrossEncoder:
        @staticmethod
        def add_custom_model(**kwargs: object) -> None:
            del kwargs
            raise ValueError("model already exists")

        def __init__(self, **kwargs: object) -> None:
            del kwargs

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace()
    )
    monkeypatch.setitem(
        sys.modules,
        "fastembed.rerank.cross_encoder",
        types.SimpleNamespace(TextCrossEncoder=TextCrossEncoder),
    )
    monkeypatch.setitem(
        sys.modules,
        "fastembed.common.model_description",
        types.SimpleNamespace(ModelSource=ModelSource),
    )
    monkeypatch.setattr(adapter_module, "_custom_model_registered", False)
    monkeypatch.setattr(adapter_module, "validate_model_artifact", lambda path: None)
    adapter_module._create_fastembed_model(RerankerSettings())
    assert adapter_module._custom_model_registered is True


def test_reranker_prefetch_uses_exact_revision_and_validates_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"pinned-avx2-artifact"
    monkeypatch.setattr(prefetch, "ONNX_MODEL_SIZE", len(payload))
    monkeypatch.setattr(prefetch, "ONNX_MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    calls: dict[str, object] = {}

    class Api:
        def model_info(self, **kwargs: object) -> object:
            calls["info"] = kwargs
            return types.SimpleNamespace(sha=RERANKER_MODEL_REVISION)

    def snapshot(**kwargs: object) -> None:
        calls["snapshot"] = kwargs
        for required_file in REQUIRED_MODEL_FILES:
            file_path = tmp_path / required_file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("metadata")
        (tmp_path / ONNX_MODEL_FILE).write_bytes(payload)

    prefetch.prefetch_model(tmp_path, api=Api(), snapshot=snapshot)
    assert calls["info"]["revision"] == RERANKER_MODEL_REVISION  # type: ignore[index]
    assert calls["snapshot"]["repo_id"] == RERANKER_MODEL_ID  # type: ignore[index]
    assert calls["snapshot"]["revision"] == RERANKER_MODEL_REVISION  # type: ignore[index]
    assert calls["snapshot"]["allow_patterns"] == list(REQUIRED_MODEL_FILES)  # type: ignore[index]


@pytest.mark.parametrize("missing_file", ("config.json", "tokenizer.json"))
def test_reranker_prefetch_rejects_missing_required_files(
    tmp_path: Path, missing_file: str
) -> None:
    for required_file in REQUIRED_MODEL_FILES:
        if required_file != missing_file:
            file_path = tmp_path / required_file
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text("metadata")
    with pytest.raises(RerankerError) as error:
        prefetch.validate_model_artifact(tmp_path)
    assert error.value.code is RerankerErrorCode.MODEL_ARTIFACT_INVALID


def test_reranker_prefetch_rejects_invalid_hash_and_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = tmp_path / ONNX_MODEL_FILE
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"not-the-pinned-model")
    with pytest.raises(RerankerError) as error:
        prefetch.validate_model_artifact(tmp_path)
    assert error.value.code is RerankerErrorCode.MODEL_ARTIFACT_INVALID

    class WrongRevisionApi:
        def model_info(self, **kwargs: object) -> object:
            del kwargs
            return types.SimpleNamespace(sha="not-pinned")

    monkeypatch.setattr(prefetch, "validate_model_artifact", lambda path: None)
    with pytest.raises(RerankerError) as revision_error:
        prefetch.prefetch_model(tmp_path, api=WrongRevisionApi(), snapshot=lambda **kwargs: None)
    assert revision_error.value.code is RerankerErrorCode.MODEL_ARTIFACT_INVALID


def test_reranker_compose_prefetch_volume_and_api_default_independence() -> None:
    compose = (Path(__file__).parents[2] / "compose.yaml").read_text(encoding="utf-8")
    prefetch_section = compose.split("  reranker-prefetch:", 1)[1].split(
        "  semantic-backfill:", 1
    )[0]
    api_section = compose.split("  api:", 1)[1].split("  ingest:", 1)[0]
    assert "reranker_model:/models/mmarco-minilm-l12-h384-int8-avx2" in prefetch_section
    assert "HF_HUB_DISABLE_XET: \"1\"" in prefetch_section
    assert "profiles: [\"tools\"]" in prefetch_section
    assert "reranker_model:" in compose
    assert "RERANKER_TIMEOUT_SECONDS: ${RERANKER_TIMEOUT_SECONDS:-5.0}" in api_section
    stress_section = compose.split("  semantic-stress:", 1)[1].split("\nvolumes:", 1)[0]
    assert "RERANKER_TIMEOUT_SECONDS: ${RERANKER_TIMEOUT_SECONDS:-5.0}" in stress_section
