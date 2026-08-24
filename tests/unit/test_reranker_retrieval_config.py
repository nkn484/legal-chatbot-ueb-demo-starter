"""Reranker retrieval feature switch is inactive by default."""

from legal_chatbot.retrieval.config import RetrievalSettings


def test_reranker_retrieval_config_defaults_false_and_accepts_alias() -> None:
    assert RetrievalSettings().rerank_enabled is False
    assert RetrievalSettings.model_validate({"RETRIEVAL_RERANK_ENABLED": "true"}).rerank_enabled
