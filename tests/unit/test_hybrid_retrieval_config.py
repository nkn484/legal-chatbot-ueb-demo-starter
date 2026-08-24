"""Semantic hybrid retrieval switch defaults remain independently opt-in."""

from legal_chatbot.retrieval.config import RetrievalSettings


def test_hybrid_retrieval_config_defaults_false_and_accepts_alias() -> None:
    assert RetrievalSettings().semantic_hybrid_enabled is False
    assert RetrievalSettings.model_validate(
        {"RETRIEVAL_SEMANTIC_HYBRID_ENABLED": "true"}
    ).semantic_hybrid_enabled
