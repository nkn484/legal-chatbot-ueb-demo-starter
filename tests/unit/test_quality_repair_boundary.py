from pathlib import Path


def test_quality_repair_package_has_no_runtime_or_adapter_imports() -> None:
    package = Path("src/legal_chatbot/retrieval/quality_repair")
    forbidden = (
        "sqlalchemy",
        "fastembed",
        "legal_chatbot.documents",
        "legal_chatbot.chat",
        "chat.planner",
        "provider",
        "llm",
        "legal_effects",
    )
    for path in package.glob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        assert not any(term in content for term in forbidden), path


def test_quality_runtime_is_bound_only_in_the_composition_root() -> None:
    runtime = Path("src/legal_chatbot/runtime/m08.py").read_text(encoding="utf-8")
    assert "quality_repair" in runtime
    assert "LegalQualityCandidatePipeline" in runtime
    assert "PostgresQualityRetrievalRepository" in runtime

    retrieval_service = Path("src/legal_chatbot/retrieval/service.py").read_text(
        encoding="utf-8"
    )
    assert "quality_repair" not in retrieval_service


def test_quality_config_does_not_import_legacy_planner_provider_or_llm() -> None:
    content = Path("src/legal_chatbot/retrieval/config.py").read_text(encoding="utf-8").lower()
    assert "chat.planner" not in content
    assert "provider" not in content
    assert "llm" not in content
