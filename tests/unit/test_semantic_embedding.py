"""Unit contracts for the isolated pinned semantic foundation."""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest

from legal_chatbot.semantic import prefetch
from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.constants import (
    ONNX_MODEL_FILE,
    REQUIRED_MODEL_FILES,
    SEMANTIC_MODEL_ID,
    SEMANTIC_MODEL_REVISION,
)
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter
from legal_chatbot.semantic.models import SemanticEmbeddingBatch, SemanticProfile


def _unit_vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * 383


def test_semantic_embedding_contract_is_exact_and_rejects_non_normalized_vector() -> None:
    assert SemanticProfile().model_id == SEMANTIC_MODEL_ID
    assert SemanticProfile().revision == SEMANTIC_MODEL_REVISION
    assert SemanticEmbeddingBatch(vectors=(_unit_vector(),)).profile.dimension == 384
    with pytest.raises(ValueError, match="L2 normalized"):
        SemanticEmbeddingBatch(vectors=((2.0,) + (0.0,) * 383,))


def test_semantic_embedding_settings_accept_csv_from_validation_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SEMANTIC_BACKFILL_SOURCE_IDS", "VBQPPL,VNU,UEB")
    settings = SemanticSettings(_env_file=None)
    assert settings.backfill_source_ids == ("VBQPPL", "VNU", "UEB")
    direct_settings = SemanticSettings(_env_file=None, backfill_source_ids=("VBQPPL",))
    assert direct_settings.backfill_source_ids == ("VBQPPL",)


@pytest.mark.parametrize(
    "source_ids",
    (("VBQPPL", "VBQPPL"), ("UNREGISTERED",)),
)
def test_semantic_embedding_settings_reject_invalid_source_tuples(
    source_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValueError, match="unique tuple from the registry"):
        SemanticSettings(_env_file=None, backfill_source_ids=source_ids)


@pytest.mark.asyncio
async def test_semantic_embedding_adapter_prefixes_inputs_lazily_without_text_state() -> None:
    received: list[tuple[str, ...]] = []

    class FakeModel:
        def embed(self, texts: tuple[str, ...], *, batch_size: int):
            assert batch_size == 16
            received.append(texts)
            return [_unit_vector() for _ in texts]

    calls = 0

    def factory(settings: SemanticSettings) -> FakeModel:
        nonlocal calls
        calls += 1
        assert settings.threads == 2
        return FakeModel()

    adapter = FastEmbedSemanticAdapter(SemanticSettings(), model_factory=factory)
    assert calls == 0
    await adapter.embed_documents(("evidence",))
    await adapter.embed_query("question")
    assert calls == 1
    assert received == [("passage: evidence",), ("query: question",)]
    assert not any("evidence" in repr(value) for value in adapter.__dict__.values())


@pytest.mark.asyncio
async def test_semantic_embedding_fastembed_registration_and_load_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import legal_chatbot.semantic.fastembed_adapter as adapter_module

    registered: list[object] = []
    constructed: list[dict[str, object]] = []

    class ModelSource:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class PoolingType:
        MEAN = "mean"

    class TextEmbedding:
        @staticmethod
        def add_custom_model(**kwargs: object) -> None:
            registered.append(kwargs)

        def __init__(self, **kwargs: object) -> None:
            constructed.append(kwargs)

        def embed(self, texts: tuple[str, ...], *, batch_size: int):
            return [_unit_vector() for _ in texts]

    monkeypatch.setitem(
        sys.modules, "fastembed", types.SimpleNamespace(TextEmbedding=TextEmbedding)
    )
    monkeypatch.setitem(
        sys.modules,
        "fastembed.common.model_description",
        types.SimpleNamespace(
            ModelSource=ModelSource,
            PoolingType=PoolingType,
        ),
    )
    monkeypatch.setattr(adapter_module, "_custom_model_registered", False)
    validated_paths: list[Path] = []

    def validate(path: Path) -> None:
        validated_paths.append(path)

    monkeypatch.setattr(adapter_module, "validate_model_artifact", validate)
    adapter = FastEmbedSemanticAdapter(SemanticSettings())
    await adapter.embed_documents(("one",))
    await adapter.embed_documents(("two",))
    assert len(registered) == 1
    assert registered[0]["pooling"] == PoolingType.MEAN  # type: ignore[index]
    assert registered[0]["normalization"] is True  # type: ignore[index]
    assert registered[0]["sources"].kwargs == {"hf": SEMANTIC_MODEL_ID}  # type: ignore[index,union-attr]
    assert validated_paths == [Path("/models/multilingual-e5-small")]
    assert constructed[0]["specific_model_path"] == "/models/multilingual-e5-small"
    assert constructed[0]["local_files_only"] is True
    assert constructed[0]["providers"] == ["CPUExecutionProvider"]


def test_semantic_embedding_adapter_rejects_incomplete_artifact_before_fastembed_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import legal_chatbot.semantic.fastembed_adapter as adapter_module

    def reject_incomplete_artifact(path: Path) -> None:
        del path
        raise SemanticError(SemanticErrorCode.MODEL_ARTIFACT_INVALID)

    monkeypatch.setattr(adapter_module, "validate_model_artifact", reject_incomplete_artifact)
    with pytest.raises(SemanticError) as error:
        adapter_module._create_fastembed_model(SemanticSettings())
    assert error.value.code is SemanticErrorCode.MODEL_ARTIFACT_INVALID


def test_semantic_embedding_prefetch_uses_exact_revision_and_validates_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"abc"
    monkeypatch.setattr(prefetch, "ONNX_MODEL_SIZE", len(payload))
    monkeypatch.setattr(prefetch, "ONNX_MODEL_SHA256", hashlib.sha256(payload).hexdigest())
    calls: dict[str, object] = {}

    class Api:
        def model_info(self, **kwargs: object) -> object:
            calls["info"] = kwargs
            return types.SimpleNamespace(sha=SEMANTIC_MODEL_REVISION)

    def snapshot(**kwargs: object) -> None:
        calls["snapshot"] = kwargs
        for required_file in REQUIRED_MODEL_FILES:
            path = tmp_path / required_file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("metadata")
        artifact = tmp_path / ONNX_MODEL_FILE
        artifact.write_bytes(payload)

    prefetch.prefetch_model(tmp_path, api=Api(), snapshot=snapshot)
    assert calls["info"]["revision"] == SEMANTIC_MODEL_REVISION  # type: ignore[index]
    assert calls["snapshot"]["repo_id"] == SEMANTIC_MODEL_ID  # type: ignore[index]
    assert calls["snapshot"]["revision"] == SEMANTIC_MODEL_REVISION  # type: ignore[index]
    assert calls["snapshot"]["allow_patterns"] == list(REQUIRED_MODEL_FILES)  # type: ignore[index]


@pytest.mark.parametrize("missing_file", ("config.json", "tokenizer.json"))
def test_semantic_embedding_prefetch_rejects_missing_required_files(
    tmp_path: Path, missing_file: str
) -> None:
    for required_file in REQUIRED_MODEL_FILES:
        if required_file == missing_file:
            continue
        path = tmp_path / required_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("metadata")
    with pytest.raises(SemanticError) as error:
        prefetch.validate_model_artifact(tmp_path)
    assert error.value.code is SemanticErrorCode.MODEL_ARTIFACT_INVALID


def test_semantic_embedding_prefetch_fails_closed_on_invalid_hash(tmp_path: Path) -> None:
    artifact = tmp_path / ONNX_MODEL_FILE
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"not-the-pinned-model")
    with pytest.raises(SemanticError) as error:
        prefetch.validate_model_artifact(tmp_path)
    assert error.value.code is SemanticErrorCode.MODEL_ARTIFACT_INVALID
