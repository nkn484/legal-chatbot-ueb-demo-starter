"""Compatibility entrypoint for the offline semantic backfill tool."""

from legal_chatbot.semantic.backfill_cli import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
