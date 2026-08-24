"""AST-level import boundary coverage for M06 Phase 1 modules only."""

from pathlib import Path

from legal_chatbot import chat

_FORBIDDEN_IMPORT_PARTS = {
    "sqlalchemy",
    "pgvector",
    "documents",
    "adapters",
    "shineshop",
    "anthropic",
    "httpx",
    "sources",
    "api",
    "logging",
    "conversation",
    "channels",
    "persistence",
}
_ALLOWED_PROVIDER_IMPORTS = {"legal_chatbot.providers.models"}


def test_phase_one_chat_modules_do_not_import_forbidden_dependencies() -> None:
    package_path = Path(chat.__file__).parent
    phase_one_modules = (
        "__init__.py",
        "models.py",
        "config.py",
        "policy.py",
        "errors.py",
        "port.py",
    )
    imports: set[str] = set()
    for module_name in phase_one_modules:
        import ast

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
    provider_imports = {
        imported
        for imported in imports
        if "providers" in imported.split(".") or "provider" in imported.split(".")
    }
    assert provider_imports <= _ALLOWED_PROVIDER_IMPORTS
