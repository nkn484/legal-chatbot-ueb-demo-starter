"""Static import and compatibility checks for the M06 grounded-chat service."""

import ast
from pathlib import Path

from legal_chatbot.chat import RetrievalPort


def test_retrieval_port_is_narrow_async_contract() -> None:
    import inspect

    assert inspect.iscoroutinefunction(RetrievalPort.retrieve)
    assert list(inspect.signature(RetrievalPort.retrieve).parameters) == ["self", "request"]


def test_service_imports_only_orchestration_contracts_and_safe_logging() -> None:
    path = Path("src/legal_chatbot/chat/service.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    allowed_prefixes = (
        "time",
        "typing",
        "uuid",
        "legal_chatbot.chat.config",
        "legal_chatbot.chat.errors",
        "legal_chatbot.chat.models",
        "legal_chatbot.chat.planner_models",
        "legal_chatbot.chat.policy",
        "legal_chatbot.chat.port",
        "legal_chatbot.chat.prompt",
        "legal_chatbot.core.logging",
        "legal_chatbot.providers.config",
        "legal_chatbot.providers.errors",
        "legal_chatbot.providers.models",
        "legal_chatbot.providers.port",
        "legal_chatbot.retrieval.models",
        "legal_chatbot.retrieval.port",
    )
    assert all(imported.startswith(allowed_prefixes) for imported in imports)
    forbidden = (
        "sqlalchemy",
        "pgvector",
        "documents",
        "adapters",
        "shineshop",
        "anthropic",
        "httpx",
        "sources",
        "api",
        "persistence",
        "conversation",
        "channels",
    )
    assert not any(part in imported.casefold() for imported in imports for part in forbidden)
    assert "m08" not in source.casefold()
    assert not any(
        field in source
        for field in (
            "conversation_id",
            "conversation_state",
            "rolling_summary",
            "active_legal_topic",
            "recent_citation_ids",
        )
    )
