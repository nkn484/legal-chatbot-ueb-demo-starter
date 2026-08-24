"""Focused source-neutral retrieval switch configuration checks."""

from legal_chatbot.retrieval.config import RetrievalSettings


def test_lexical_repair_defaults_disabled_and_accepts_explicit_environment_alias() -> None:
    assert RetrievalSettings().lexical_repair_enabled is False
    enabled = RetrievalSettings.model_validate({"RETRIEVAL_LEXICAL_REPAIR_ENABLED": "true"})
    assert enabled.lexical_repair_enabled
