"""Persistence models for source-backed legal documents."""

from legal_chatbot.documents.citation_resolver import PostgresCitationResolver
from legal_chatbot.documents.grounding_evidence import PostgresGroundingEvidenceAdapter
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    SourceProvenanceRecord,
)
from legal_chatbot.documents.repository import DocumentRepository
from legal_chatbot.documents.retrieval_repository import PostgresLexicalRetrievalRepository

__all__ = [
    "CitationRecord",
    "ChunkEmbedding",
    "DocumentChunk",
    "DocumentVersion",
    "DocumentRepository",
    "LegalDocument",
    "PostgresCitationResolver",
    "PostgresGroundingEvidenceAdapter",
    "PostgresLexicalRetrievalRepository",
    "RetrievalRun",
    "SourceProvenanceRecord",
]
