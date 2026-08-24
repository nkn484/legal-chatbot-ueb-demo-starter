"""Offline semantic foundation, isolated from live retrieval and chat runtime."""

from legal_chatbot.semantic.config import SemanticSettings
from legal_chatbot.semantic.errors import SemanticError, SemanticErrorCode
from legal_chatbot.semantic.fastembed_adapter import FastEmbedSemanticAdapter
from legal_chatbot.semantic.models import SemanticEmbeddingBatch, SemanticProfile
from legal_chatbot.semantic.ports import SemanticEmbeddingPort

__all__ = [
    "FastEmbedSemanticAdapter",
    "SemanticEmbeddingBatch",
    "SemanticEmbeddingPort",
    "SemanticError",
    "SemanticErrorCode",
    "SemanticProfile",
    "SemanticSettings",
]
