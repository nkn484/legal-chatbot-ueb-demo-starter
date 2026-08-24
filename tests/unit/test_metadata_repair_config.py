"""Metadata repair is explicitly disabled until evaluation activation."""

from legal_chatbot.retrieval.config import RetrievalSettings


def test_metadata_repair_config_defaults_disabled_and_accepts_alias() -> None:
    assert RetrievalSettings().metadata_repair_enabled is False
    assert RetrievalSettings.model_validate(
        {"RETRIEVAL_METADATA_REPAIR_ENABLED": "true"}
    ).metadata_repair_enabled
