"""Lazy CPU FastEmbed implementation of the fixed cross-encoder reranker port."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from threading import Lock
from typing import Any

from legal_chatbot.reranking.config import RerankerSettings
from legal_chatbot.reranking.constants import (
    ONNX_MODEL_FILE,
    RERANKER_LICENSE,
    RERANKER_MODEL_ID,
)
from legal_chatbot.reranking.errors import RerankerError, RerankerErrorCode
from legal_chatbot.reranking.models import RerankRequest, RerankResult
from legal_chatbot.reranking.prefetch import validate_model_artifact

_registration_lock = Lock()
_custom_model_registered = False


def _create_fastembed_model(settings: RerankerSettings) -> Any:
    """Register the exact custom model once and construct a local CPU runner."""

    global _custom_model_registered
    validate_model_artifact(settings.model_path)
    try:
        from fastembed.common.model_description import ModelSource
        from fastembed.rerank.cross_encoder import TextCrossEncoder
    except ImportError as error:
        raise RerankerError(RerankerErrorCode.MODEL_UNAVAILABLE) from error

    with _registration_lock:
        if not _custom_model_registered:
            try:
                TextCrossEncoder.add_custom_model(
                    model=RERANKER_MODEL_ID,
                    sources=ModelSource(hf=RERANKER_MODEL_ID),
                    model_file=ONNX_MODEL_FILE,
                    license=RERANKER_LICENSE,
                )
            except ValueError as error:
                if "already" not in str(error).lower() and "exist" not in str(error).lower():
                    raise RerankerError(RerankerErrorCode.MODEL_UNAVAILABLE) from error
            _custom_model_registered = True
    try:
        return TextCrossEncoder(
            model_name=RERANKER_MODEL_ID,
            specific_model_path=settings.model_path.as_posix(),
            local_files_only=True,
            providers=["CPUExecutionProvider"],
            threads=settings.threads,
        )
    except Exception as error:
        raise RerankerError(RerankerErrorCode.MODEL_UNAVAILABLE) from error


class FastEmbedRerankerAdapter:
    """Load only on use; no query or hydrated candidate text is retained or logged."""

    def __init__(
        self,
        settings: RerankerSettings,
        *,
        model_factory: Callable[[RerankerSettings], Any] = _create_fastembed_model,
    ) -> None:
        self._settings = settings
        self._model_factory = model_factory
        self._model: Any | None = None
        self._model_lock = Lock()

    async def rerank(self, request: RerankRequest) -> RerankResult:
        """Run exactly one raw-logit model call in a worker thread without retries."""

        self._validate_request_bounds(request)
        return await asyncio.to_thread(self._rerank_sync, request)

    def _validate_request_bounds(self, request: RerankRequest) -> None:
        if (
            len(request.query) > self._settings.query_max_chars
            or len(request.candidates) > self._settings.candidate_max
            or len(request.candidates) > self._settings.batch_size
            or any(
                len(candidate.text) > self._settings.hydrated_text_max_chars
                for candidate in request.candidates
            )
        ):
            raise RerankerError(RerankerErrorCode.INVALID_INPUT)

    def _rerank_sync(self, request: RerankRequest) -> RerankResult:
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    self._model = self._model_factory(self._settings)
        try:
            model = self._model
            if model is None:
                raise RerankerError(RerankerErrorCode.MODEL_UNAVAILABLE)
            scores = tuple(
                float(score)
                for score in model.rerank(
                    request.query,
                    tuple(candidate.text for candidate in request.candidates),
                    batch_size=self._settings.batch_size,
                )
            )
            return RerankResult.from_request(request, scores)
        except RerankerError:
            raise
        except ValueError as error:
            raise RerankerError(RerankerErrorCode.INVALID_RESULT) from error
        except Exception as error:
            raise RerankerError(RerankerErrorCode.RERANK_FAILED) from error
