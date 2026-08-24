"""Generic M07 conversation-context seam coverage without a conversation dependency."""

import ast
from pathlib import Path

from legal_chatbot.chat import ChatRequest, ConversationContext, ConversationContextTurn


def test_generic_context_has_no_conversation_identifier_or_state_fields() -> None:
    request = ChatRequest(
        question="current question",
        conversation_context=ConversationContext(
            recent_turns=(ConversationContextTurn(role="USER", text="previous turn", ordinal=1),),
        ),
    )

    assert request.conversation_context is not None
    assert set(type(request.conversation_context).model_fields) == {
        "rolling_summary",
        "active_topic",
        "recent_turns",
    }
    assert "conversation_id" not in type(request).model_fields


def test_chat_modules_do_not_import_the_conversation_package() -> None:
    package_path = Path("src/legal_chatbot/chat")
    for module_name in ("models.py", "config.py", "prompt.py", "service.py", "__init__.py"):
        tree = ast.parse((package_path / module_name).read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any("conversation" in imported.casefold() for imported in imports)
