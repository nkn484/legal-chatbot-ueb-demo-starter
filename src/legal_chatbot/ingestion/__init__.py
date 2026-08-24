"""Source-neutral ingestion normalization contracts."""

from legal_chatbot.ingestion.chunking import DeterministicChunker
from legal_chatbot.ingestion.config import IngestionSettings
from legal_chatbot.ingestion.embedding import EmbeddingPort, LocalHashEmbeddingAdapter
from legal_chatbot.ingestion.models import (
    ChunkDraft,
    EmbeddingBatch,
    EmbeddingKind,
    IngestionOutcome,
    IngestionResult,
    NormalizedBlock,
    NormalizedDocument,
)
from legal_chatbot.ingestion.normalization import HTMLNormalizer
from legal_chatbot.ingestion.service import IngestionService, canonical_snapshot_sha256

__all__ = [
    "ChunkDraft",
    "DeterministicChunker",
    "EmbeddingBatch",
    "EmbeddingKind",
    "EmbeddingPort",
    "HTMLNormalizer",
    "IngestionOutcome",
    "IngestionResult",
    "IngestionSettings",
    "IngestionService",
    "LocalHashEmbeddingAdapter",
    "NormalizedBlock",
    "NormalizedDocument",
    "canonical_snapshot_sha256",
]
