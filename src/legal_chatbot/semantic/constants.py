"""Immutable, provider-neutral multilingual E5 semantic profile constants."""

from __future__ import annotations

SEMANTIC_MODEL_ID = "intfloat/multilingual-e5-small"
SEMANTIC_MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
SEMANTIC_PROFILE_ID = "e5-small-384-mean-l2-prefix-v1"
SEMANTIC_DIMENSION = 384
SEMANTIC_POOLING = "mean"
SEMANTIC_NORMALIZATION = "l2"
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
ONNX_MODEL_FILE = "onnx/model.onnx"
ONNX_MODEL_SIZE = 470_268_510
ONNX_MODEL_SHA256 = "ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665"
REQUIRED_MODEL_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    ONNX_MODEL_FILE,
)
