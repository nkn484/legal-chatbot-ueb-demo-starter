import pytest

from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.channels.recipients import OfficialBotRecipientRegistry
from legal_chatbot.legal_evidence.channel_bridge import LegalChatGroundedChatBridge
from legal_chatbot.legal_evidence.integration_config import LegalChatIntegrationSettings
from legal_chatbot.providers.config import ProviderSettings
from legal_chatbot.runtime.m08 import build_m08_runtime


class _Channel:
    async def aclose(self) -> None:
        return None


class _Ingress:
    async def handle_inbound(self, message, now):
        del message, now
        raise AssertionError("not invoked during composition")


@pytest.mark.asyncio
async def test_m08_reuses_existing_channel_composition_with_legal_application_bridge() -> None:
    captured = {}

    def conversation_service_factory(repository, grounded_chat, resolver, settings):
        del repository, resolver, settings
        captured["grounded_chat"] = grounded_chat
        return object()

    def channel_service_factory(*args):
        captured["channel_service_args"] = args
        return _Ingress()

    runtime = await build_m08_runtime(
        object(),
        ChannelSettings(
            CHANNEL_ENABLED=True,
            ZALO_OFFICIAL_BOT_TOKEN="a" * 32,
            ZALO_OFFICIAL_BOT_WEBHOOK_SECRET="b" * 32,
            CHANNEL_IDENTITY_HMAC_KEY="c" * 64,
        ),
        provider_settings=ProviderSettings(
            LLM_BASE_URL="https://provider.example/v1",
            LLM_MODEL="legacy-model",
            LLM_API_KEY="test-key",
        ),
        legal_chat_integration_settings=LegalChatIntegrationSettings(
            LEGAL_CHAT_PIPELINE_ENABLED=True
        ),
        session_factory_factory=lambda engine: object(),
        semantic_embedder_factory=lambda settings: object(),
        citation_resolver_factory=lambda sessions: object(),
        conversation_repository_factory=lambda sessions, settings: object(),
        conversation_service_factory=conversation_service_factory,
        binding_repository_factory=lambda sessions, settings: object(),
        outbound_repository_factory=lambda sessions, settings: object(),
        formatter_factory=lambda settings: object(),
        recipient_registry_factory=OfficialBotRecipientRegistry,
        channel_factory=lambda settings, recipients: _Channel(),
        channel_service_factory=channel_service_factory,
    )

    assert runtime is not None
    assert isinstance(captured["grounded_chat"], LegalChatGroundedChatBridge)
    assert runtime.provider is None
    await runtime.aclose()
