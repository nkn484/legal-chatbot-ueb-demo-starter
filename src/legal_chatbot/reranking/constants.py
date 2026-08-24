"""Immutable identity and artifact constants for the offline reranker profile."""

from __future__ import annotations

RERANKER_MODEL_ID = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
RERANKER_MODEL_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
RERANKER_PROFILE_ID = "mmarco-minilm-l12-h384-int8-avx2-v1"
RERANKER_LICENSE = "Apache-2.0"
ONNX_MODEL_FILE = "onnx/model_quint8_avx2.onnx"
ONNX_MODEL_SIZE = 118_620_016
ONNX_MODEL_SHA256 = "6c2513767fb63d008a4377bef7a7a3555433d9436342bb53e35a3a72ffc52d4b"
REQUIRED_MODEL_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    ONNX_MODEL_FILE,
)
RERANKER_BATCH_SIZE = 8
RERANKER_THREADS = 2
RERANKER_CANDIDATE_MAX = 8
RERANKER_QUERY_MAX_CHARS = 4_000
RERANKER_HYDRATED_TEXT_MAX_CHARS = 2_000
RERANKER_TIMEOUT_SECONDS = 5.0
