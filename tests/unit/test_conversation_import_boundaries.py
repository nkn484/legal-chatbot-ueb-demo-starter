"""AST-level import boundary coverage for M07 Phase 1 modules only."""

import ast
from pathlib import Path

from legal_chatbot import conversation

_FORBIDDEN_IMPORT_PARTS = {
    "sqlalchemy",
    "pgvector",
    "documents",
    "adapters",
    "shineshop",
    "anthropic",
    "providers",
    "sources",
    "api",
    "logging",
    "channels",
    "zalo",
    "persistence",
    "repository",
    "service",
    "m08",
}


def test_phase_one_conversation_modules_do_not_import_forbidden_dependencies() -> None:
    package_path = Path(conversation.__file__).parent
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


def test_package_exports_do_not_import_or_expose_persistence_concerns() -> None:
    init_path = Path(conversation.__file__)
    tree = ast.parse(init_path.read_text(encoding="utf-8"))
    imports = {
        imported
        for node in ast.walk(tree)
        for imported in (
            [alias.name for alias in node.names]
            if isinstance(node, ast.Import)
            else [node.module]
            if isinstance(node, ast.ImportFrom) and node.module
            else []
        )
    }
    exported_names = {
        element.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
        and isinstance(node.value, (ast.List, ast.Tuple))
        for element in node.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }

    forbidden_import_parts = {"orm", "sqlalchemy", "repository", "service"}
    assert not {
        part
        for imported in imports
        for part in imported.split(".")
        if part.casefold() in forbidden_import_parts
    }
    assert not {
        name
        for name in exported_names
        if name.casefold() in {"orm", "sqlalchemy", "repository", "service"}
    }
