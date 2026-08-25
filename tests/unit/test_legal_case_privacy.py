from pathlib import Path


def test_legal_evidence_domain_has_no_runtime_or_adapter_imports() -> None:
    package = Path("src/legal_chatbot/legal_evidence")
    prohibited = (
        "sqlalchemy",
        "asyncpg",
        "httpx",
        "legal_chatbot.documents",
        "legal_chatbot.providers",
        "legal_chatbot.sources",
        "legal_chatbot.channels",
        "legal_chatbot.runtime",
    )

    pure_contract_modules = (
        "__init__.py",
        "compatibility.py",
        "context.py",
        "models.py",
        "ports.py",
        "transitions.py",
    )
    for filename in pure_contract_modules:
        path = package / filename
        content = path.read_text(encoding="utf-8")
        assert all(marker not in content for marker in prohibited), path


def test_legal_evidence_domain_does_not_expose_private_text_in_public_helpers() -> None:
    source = Path("src/legal_chatbot/legal_evidence/models.py").read_text(encoding="utf-8")

    assert "question_text: str" in source
    assert "max_length=4_000, exclude=True, repr=False" in source
    assert "text: str" in source
    assert "max_length=20_000, exclude=True, repr=False" in source
    assert "locator: str" in source
    assert "max_length=512, exclude=True, repr=False" in source
