"""Bounded PDF text extraction with an optional local OCR fallback."""

from __future__ import annotations

import html
import io
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol

import pymupdf
from pypdf import PdfReader

from legal_chatbot.demo_corpus.models import ExtractedDocument, ExtractedPage


class OCRAdapter(Protocol):
    def available(self) -> bool: ...

    def extract(self, pdf: bytes) -> tuple[str, ...]: ...


class OCRRequiredError(ValueError):
    """Raised when a PDF has no useful text layer and OCR cannot run."""


@dataclass(frozen=True)
class TesseractOCRAdapter:
    executable: str = "tesseract"
    language: str = "vie+eng"
    timeout_seconds_per_page: float = 45.0
    max_pages: int = 300

    def available(self) -> bool:
        return shutil.which(self.executable) is not None

    def extract(self, pdf: bytes) -> tuple[str, ...]:
        if not self.available():
            raise OCRRequiredError("ocr_unavailable")
        document = pymupdf.open(stream=pdf, filetype="pdf")
        try:
            if len(document) > self.max_pages:
                raise OCRRequiredError("ocr_page_limit_exceeded")
            pages: list[str] = []
            for page in document:
                png = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")
                process = subprocess.run(
                    [
                        self.executable,
                        "stdin",
                        "stdout",
                        "-l",
                        self.language,
                        "--psm",
                        "6",
                    ],
                    input=png,
                    capture_output=True,
                    check=False,
                    timeout=self.timeout_seconds_per_page,
                )
                if process.returncode != 0:
                    raise OCRRequiredError("ocr_command_failed")
                pages.append(process.stdout.decode("utf-8", errors="replace").strip())
            return tuple(pages)
        finally:
            document.close()


class PDFTextExtractor:
    def __init__(
        self,
        ocr: OCRAdapter | None = None,
        *,
        minimum_total_chars: int = 100,
        max_pages: int = 500,
    ) -> None:
        self._ocr = ocr
        self._minimum_total_chars = minimum_total_chars
        self._max_pages = max_pages

    def extract(self, pdf: bytes) -> ExtractedDocument:
        if not pdf.startswith(b"%PDF"):
            raise ValueError("asset_is_not_pdf")
        reader = PdfReader(io.BytesIO(pdf))
        if not 1 <= len(reader.pages) <= self._max_pages:
            raise ValueError("pdf_page_count_out_of_bounds")
        text_pages = tuple((page.extract_text() or "").strip() for page in reader.pages)
        if sum(len(value) for value in text_pages) < self._minimum_total_chars:
            if self._ocr is None or not self._ocr.available():
                raise OCRRequiredError("ocr_required")
            text_pages = self._ocr.extract(pdf)
            used_ocr = True
        else:
            used_ocr = False
        if not any(value.strip() for value in text_pages):
            raise OCRRequiredError("ocr_empty")
        return ExtractedDocument(
            pages=tuple(
                ExtractedPage(page_number=index, text=value)
                for index, value in enumerate(text_pages, start=1)
            ),
            used_ocr=used_ocr,
        )


def render_extracted_html(document: ExtractedDocument) -> str:
    blocks = []
    for page in document.pages:
        if not page.text.strip():
            continue
        blocks.append(
            '<section class="prov-section" data-label="Trang '
            f'{page.page_number}"><p>{html.escape(page.text)}</p></section>'
        )
    if not blocks:
        raise ValueError("extracted_document_has_no_text")
    return "<article>" + "".join(blocks) + "</article>"
