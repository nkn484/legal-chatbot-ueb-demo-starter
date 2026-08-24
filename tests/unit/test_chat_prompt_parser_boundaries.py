"""AST import-boundary coverage for the M06 Phase 3 prompt and parser modules."""

import ast
from pathlib import Path

from legal_chatbot import chat

_FORBIDDEN_IMPORT_PARTS = {
    "providers",
    "provider",
    "sqlalchemy",
    "pgvector",
    "documents",
    "httpx",
    "logging",
    "api",
    "sources",
    "conversation",
    "channels",
    "service",
}


def test_prompt_and_parser_import_only_stdlib_and_chat_contracts() -> None:
    package_path = Path(chat.__file__).parent
    imports: set[str] = set()
    for module_name in ("prompt.py", "parser.py"):
        tree = ast.parse((package_path / module_name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

    assert not {
        part
        for imported in imports
        for part in imported.split(".")
        if part.casefold() in _FORBIDDEN_IMPORT_PARTS
    }
    assert all(
        imported.startswith(("json", "typing", "unicodedata", "legal_chatbot.chat"))
        for imported in imports
    )
