"""Metadata repair runtime selection remains explicit and fail-closed."""

from legal_chatbot.retrieval.config import RetrievalSettings


def test_metadata_repair_requires_explicit_semantic_and_rerank_switches() -> None:
    settings = RetrievalSettings(metadata_repair_enabled=True)
    assert settings.metadata_repair_enabled is True
    assert settings.semantic_hybrid_enabled is False
    assert settings.rerank_enabled is False
