"""AST import-boundary coverage for the M07 Phase 3 conversation service."""

import ast
from pathlib import Path


def test_service_imports_only_contracts_policy_citation_resolution_and_safe_logging() -> None:
    path = Path("src/legal_chatbot/conversation/service.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    allowed_prefixes = (
        "datetime",
        "time",
        "typing",
        "uuid",
        "legal_chatbot.chat.models",
        "legal_chatbot.chat.policy",
        "legal_chatbot.conversation.errors",
        "legal_chatbot.conversation.models",
        "legal_chatbot.conversation.policy",
        "legal_chatbot.conversation.port",
        "legal_chatbot.core.logging",
        "legal_chatbot.retrieval.models",
        "legal_chatbot.retrieval.port",
    )
    assert all(imported.startswith(allowed_prefixes) for imported in imports)
    forbidden_parts = {
        "sqlalchemy",
        "documents",
        "providers",
        "sources",
        "channels",
        "api",
        "httpx",
        "repository",
        "m08",
    }
    assert not {
        part
        for imported in imports
        for part in imported.split(".")
        if part.casefold() in forbidden_parts
    }
    assert "conversation_id" not in source[source.index("def _log") :]
