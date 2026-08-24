"""ASGI export and executable Uvicorn entry point."""

import uvicorn

from legal_chatbot.api.app import app, create_app
from legal_chatbot.channels.config import ChannelSettings
from legal_chatbot.core.config import Settings
from legal_chatbot.core.logging import configure_logging


def main() -> None:
    """Start Uvicorn after validating settings and installing JSON logging."""
    settings = Settings()
    channel_settings = ChannelSettings()
    configure_logging(settings.log_level)
    if channel_settings.enabled:
        from functools import partial

        from legal_chatbot.runtime.m08 import build_m08_runtime

        runtime_factory = partial(build_m08_runtime, channel_settings=channel_settings)
        application = create_app(
            settings=settings,
            channel_settings=channel_settings,
            channel_runtime_factory=runtime_factory,
        )
    else:
        application = create_app(settings=settings, channel_settings=channel_settings)
    uvicorn.run(
        application,
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
