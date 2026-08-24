"""Focused protocol signature coverage for M07 Phase 1."""

import inspect

from legal_chatbot.conversation import ConversationRepositoryPort, GroundedChatPort


def test_grounded_chat_port_respond_is_async_with_only_a_chat_request() -> None:
    assert inspect.iscoroutinefunction(GroundedChatPort.respond)
    assert list(inspect.signature(GroundedChatPort.respond).parameters) == ["self", "request"]


def test_conversation_repository_port_methods_are_async_and_bounded() -> None:
    expected_parameters = {
        "create_conversation": ["self", "now"],
        "reserve": ["self", "request", "now"],
        "load_snapshot": ["self", "conversation_id", "now"],
        "complete": ["self", "reservation", "chat", "state_update", "now"],
        "purge_expired": ["self", "now", "limit"],
    }

    for method_name, parameters in expected_parameters.items():
        method = getattr(ConversationRepositoryPort, method_name)
        assert inspect.iscoroutinefunction(method)
        assert list(inspect.signature(method).parameters) == parameters
