"""Lazy CPU FastEmbed implementation of the fixed E5 semantic port."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from threading import Lock
from typing import Any

from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.constants import (
    ONNX_MODEL_FILE,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    SEMANTIC_DIMENSION,
    SEMANTIC_MODEL_ID,
)
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode
from legal_chatbot.semantic.models import SemanticEmbeddingBatch
from legal_chatbot.semantic.prefetch import validate_model_artifact

_registration_lock = Lock()
_custom_model_registered = False


def _create_fastembed_model(settings: SemanticSettings) -> Any:
    """Register the exact model once and construct a local-files-only CPU runner."""

    global _custom_model_registered
    validate_model_artifact(settings.model_path)
    try:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import ModelSource, PoolingType
    except ImportError as error:
        raise SemanticError(SemanticErrorCode.MODEL_UNAVAILABLE) from error

    with _registration_lock:
        if not _custom_model_registered:
            TextEmbedding.add_custom_model(
                model=SEMANTIC_MODEL_ID,
                sources=ModelSource(hf=SEMANTIC_MODEL_ID),
                model_file=ONNX_MODEL_FILE,
                dim=SEMANTIC_DIMENSION,
                pooling=PoolingType.MEAN,
                normalization=True,
            )
            _custom_model_registered = True
    try:
        return TextEmbedding(
            model_name=SEMANTIC_MODEL_ID,
            specific_model_path=settings.model_path.as_posix(),
            local_files_only=True,
            providers=["CPUExecutionProvider"],
            threads=settings.threads,
        )
    except Exception as error:
        raise SemanticError(SemanticErrorCode.MODEL_UNAVAILABLE) from error


class FastEmbedSemanticAdapter:
    """Use FastEmbed only on demand; input text is never stored or logged."""

    def __init__(
        self,
        settings: SemanticSettings,
        *,
        model_factory: Callable[[SemanticSettings], Any] = _create_fastembed_model,
    ) -> None:
        self._settings = settings
        self._model_factory = model_factory
        self._model: Any | None = None
        self._model_lock = Lock()

    async def embed_documents(self, texts: Sequence[str]) -> SemanticEmbeddingBatch:
        """Embed passages with the mandatory E5 passage prefix."""

        prefixed = self._prefixed_texts(texts, PASSAGE_PREFIX)
        return await asyncio.to_thread(self._embed_sync, prefixed)

    async def embed_query(self, text: str) -> SemanticEmbeddingBatch:
        """Embed one query with the mandatory E5 query prefix."""

        prefixed = self._prefixed_texts((text,), QUERY_PREFIX)
        return await asyncio.to_thread(self._embed_sync, prefixed)

    def _prefixed_texts(self, texts: Sequence[str], prefix: str) -> tuple[str, ...]:
        if isinstance(texts, str) or not texts or len(texts) > self._settings.batch_size:
            raise SemanticError(SemanticErrorCode.INVALID_INPUT)
        if any(not isinstance(item, str) or not item.strip() for item in texts):
            raise SemanticError(SemanticErrorCode.INVALID_INPUT)
        return tuple(prefix + item for item in texts)

    def _embed_sync(self, prefixed_texts: tuple[str, ...]) -> SemanticEmbeddingBatch:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    self._model = self._model_factory(self._settings)
        try:
            model = self._model
            if model is None:
                raise SemanticError(SemanticErrorCode.MODEL_UNAVAILABLE)
            raw_vectors = model.embed(prefixed_texts, batch_size=self._settings.batch_size)
            vectors = tuple(tuple(float(value) for value in vector) for vector in raw_vectors)
            return SemanticEmbeddingBatch(vectors=vectors)
        except SemanticError:
            raise
        except ValueError as error:
            raise SemanticError(SemanticErrorCode.INVALID_VECTOR) from error
        except Exception as error:
            raise SemanticError(SemanticErrorCode.EMBEDDING_FAILED) from error
