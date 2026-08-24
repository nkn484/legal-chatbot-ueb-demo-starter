"""Approved manual-snapshot corpus import for the UEB demo."""

from legal_chatbot.demo_corpus.models import (
    CatalogEntry,
    CorpusFileKind,
    CorpusProcessingStatus,
    ExtractedDocument,
    ExtractedPage,
)
from legal_chatbot.demo_corpus.pdf import PDFTextExtractor, TesseractOCRAdapter
from legal_chatbot.demo_corpus.workbook import load_demo_catalog

__all__ = [
    "CatalogEntry",
    "CorpusFileKind",
    "CorpusProcessingStatus",
    "ExtractedDocument",
    "ExtractedPage",
    "PDFTextExtractor",
    "TesseractOCRAdapter",
    "load_demo_catalog",
]
