"""Unit evidence for the approved workbook/PDF manual snapshot lane."""

from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest

from legal_chatbot.channels.formatter import ChannelFormatter
from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.demo_corpus.models import CorpusFileKind
from legal_chatbot.demo_corpus.pdf import OCRRequiredError, PDFTextExtractor, render_extracted_html
from legal_chatbot.demo_corpus.workbook import (
    classify_file_reference,
    direct_download_url,
    load_demo_catalog,
)
from legal_chatbot.retrieval.models import (
    EvidenceTrustLabel,
    ResolvedCitation,
    evidence_trust_label_for,
)
from legal_chatbot.sources.models import ProvenanceType, TransportTrustMode


def _pdf(text: str | None) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    if text is not None:
        page.insert_text((72, 72), text)
    value = document.tobytes()
    document.close()
    return value


def test_repository_demo_data_has_the_approved_1104_rows() -> None:
    entries = load_demo_catalog(Path("demo_data"))

    assert len(entries) == 1_104
    assert {
        source: sum(entry.source_id == source for entry in entries)
        for source in {"VBQPPL", "VNU", "UEB"}
    } == {
        "VBQPPL": 452,
        "VNU": 307,
        "UEB": 345,
    }
    assert len({entry.external_id for entry in entries}) == 1_104
    assert all(len(entry.record_sha256) == 64 for entry in entries)


def test_file_reference_classification_and_direct_urls_are_fail_closed() -> None:
    drive = "https://drive.google.com/file/d/file-id/view?usp=drive_link"
    document = "https://docs.google.com/document/d/doc-id/edit?usp=drive_link"
    folder = "https://drive.google.com/drive/folders/folder-id"

    assert classify_file_reference("1/QĐ", drive) is CorpusFileKind.DIRECT_FILE
    assert classify_file_reference("1/QĐ", document) is CorpusFileKind.DIRECT_FILE
    assert classify_file_reference("1/QĐ", folder) is CorpusFileKind.FOLDER
    assert classify_file_reference("1/QĐ", None) is CorpusFileKind.UNRESOLVED
    assert classify_file_reference(None, None) is CorpusFileKind.MISSING
    assert direct_download_url(drive) == (
        "https://drive.usercontent.google.com/download?id=file-id&export=download"
    )
    assert direct_download_url(document) == (
        "https://docs.google.com/document/d/doc-id/export?format=pdf"
    )
    assert direct_download_url(folder) is None


def test_pdf_text_extraction_preserves_page_locator_and_requires_real_ocr() -> None:
    extracted = PDFTextExtractor(minimum_total_chars=10).extract(
        _pdf("This is a sufficiently long legal text layer for extraction.")
    )
    html = render_extracted_html(extracted)

    assert extracted.used_ocr is False
    assert extracted.pages[0].page_number == 1
    assert "Trang 1" in html
    assert "legal text layer" in html
    with pytest.raises(OCRRequiredError, match="ocr_required"):
        PDFTextExtractor(minimum_total_chars=10).extract(_pdf(None))


def test_manual_snapshot_transport_is_never_labeled_official() -> None:
    assert (
        evidence_trust_label_for(TransportTrustMode.STRICT_TLS, ProvenanceType.MANUAL_SNAPSHOT)
        is EvidenceTrustLabel.MANUAL_SNAPSHOT
    )
    assert (
        evidence_trust_label_for(TransportTrustMode.STRICT_TLS, ProvenanceType.SOURCE_FETCH)
        is EvidenceTrustLabel.OFFICIAL_LEGAL
    )
    with pytest.raises(ValueError, match="not eligible"):
        evidence_trust_label_for(
            TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION,
            ProvenanceType.MANUAL_SNAPSHOT,
        )

    citation = ResolvedCitation(
        citation_id=uuid4(),
        retrieval_run_id=uuid4(),
        document_chunk_id=uuid4(),
        document_version_id=uuid4(),
        document_id=uuid4(),
        source_provenance_record_id=uuid4(),
        provenance_type=ProvenanceType.MANUAL_SNAPSHOT,
        transport_trust_mode=TransportTrustMode.STRICT_TLS,
        evidence_trust_label=EvidenceTrustLabel.MANUAL_SNAPSHOT,
        source_id="UEB",
        external_id="demo-data-v1:RAWDATA_UEB:2",
        document_number="821/QĐ-ĐHKT",
    )
    rendered = ChannelFormatter._format_citation(citation)
    assert "nhập thủ công cho demo" in rendered
    assert "chính thức" in rendered


def test_demo_corpus_settings_enable_only_bounded_registered_ids() -> None:
    assert DemoCorpusSettings(retrieval_source_ids_csv="VBQPPL,VNU,UEB").retrieval_source_ids() == (
        "VBQPPL",
        "VNU",
        "UEB",
    )
    with pytest.raises(ValueError, match="INVALID"):
        DemoCorpusSettings(retrieval_source_ids_csv="VBQPPL,UNKNOWN").retrieval_source_ids()
