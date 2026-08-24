"""Pure contracts, ports, errors, and ranking helpers for M05 retrieval evidence."""

from legal_chatbot.retrieval.benchmark_metrics import (
    MAX_BENCHMARK_K,
    BenchmarkComparison,
    BenchmarkMetrics,
    BenchmarkMode,
    BenchmarkObservation,
    FallbackKind,
    aggregate_benchmark_metrics,
    compare_benchmark_modes,
)
from legal_chatbot.retrieval.errors import RetrievalError, RetrievalErrorCode
from legal_chatbot.retrieval.models import (
    EXPANSION_DOCUMENT_IDS_MAX_COUNT,
    EXPANSION_QUERY_MAX_CHARS,
    LEXICAL_STRATEGY,
    LEXICAL_STRATEGY_VERSION,
    QUERY_MAX_CHARS,
    ResolvedCitation,
    RetrievalCandidate,
    RetrievalDecision,
    RetrievalReason,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScope,
    TemporalScope,
)
from legal_chatbot.retrieval.port import CitationResolverPort, RetrievalRepositoryPort
from legal_chatbot.retrieval.service import RetrievalService

__all__ = [
    "CitationResolverPort",
    "BenchmarkComparison",
    "BenchmarkMetrics",
    "BenchmarkMode",
    "BenchmarkObservation",
    "EXPANSION_DOCUMENT_IDS_MAX_COUNT",
    "EXPANSION_QUERY_MAX_CHARS",
    "LEXICAL_STRATEGY",
    "LEXICAL_STRATEGY_VERSION",
    "MAX_BENCHMARK_K",
    "QUERY_MAX_CHARS",
    "ResolvedCitation",
    "RetrievalCandidate",
    "RetrievalDecision",
    "RetrievalError",
    "RetrievalErrorCode",
    "RetrievalReason",
    "RetrievalRepositoryPort",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalService",
    "RetrievalScope",
    "TemporalScope",
    "FallbackKind",
    "aggregate_benchmark_metrics",
    "compare_benchmark_modes",
]
