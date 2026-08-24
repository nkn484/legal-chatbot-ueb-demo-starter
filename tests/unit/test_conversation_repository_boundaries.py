"""Import-boundary checks for the M07 repository adapter."""

import ast
from pathlib import Path

_REPOSITORY_PATH = (
    Path(__file__).resolve().parents[2] / "src" / "legal_chatbot" / "conversation" / "repository.py"
)
_FORBIDDEN_MODULE_PARTS = {
    "api",
    "channel",
    "channels",
    "httpx",
    "logging",
    "providers",
    "sources",
}


def test_repository_imports_only_persistence_and_conversation_contract_boundaries() -> None:
    tree = ast.parse(_REPOSITORY_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )

    assert "sqlalchemy" in imports
    source = _REPOSITORY_PATH.read_text(encoding="utf-8")
    assert not any(f"legal_chatbot.{part}" in source for part in _FORBIDDEN_MODULE_PARTS)
    assert "legal_chatbot.chat.service" not in source
    assert "legal_chatbot.retrieval.service" not in source
    assert "legal_chatbot.m08" not in source
    assert "open(" not in source
    assert "subprocess" not in source
