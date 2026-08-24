"""Static boundary checks for the grounding evidence read adapter."""

from __future__ import annotations

import ast
from pathlib import Path


def test_grounding_evidence_adapter_stays_read_only_and_dependency_narrow() -> None:
    path = Path("src/legal_chatbot/documents/grounding_evidence.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    forbidden_import_parts = (
        "pgvector",
        "embedding",
        "vector",
        "rrf",
        "provider",
        "sources",
        "api",
        "logging",
        "prompt",
        "service",
        "conversation",
        "channel",
    )
    assert not any(
        part in module.lower() for module in imported_modules for part in forbidden_import_parts
    )
    assert "sqlalchemy" in imported_modules
    assert "legal_chatbot.documents.orm" in imported_modules

    forbidden_calls = {"add", "add_all", "commit", "delete", "flush", "merge", "remove"}
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & forbidden_calls
    source = path.read_text(encoding="utf-8").lower()
    assert "insert(" not in source
    assert "update(" not in source
