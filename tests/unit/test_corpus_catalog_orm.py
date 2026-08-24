"""Metadata-only checks for manual corpus catalog persistence."""

from typing import cast

from sqlalchemy import Table

from legal_chatbot.documents.orm import CorpusCatalogEntry, CorpusIngestionRun


def test_corpus_catalog_tables_have_bounded_identity_status_and_links() -> None:
    entry = cast(Table, CorpusCatalogEntry.__table__)
    run = cast(Table, CorpusIngestionRun.__table__)

    assert entry.name == "corpus_catalog_entries"
    assert run.name == "corpus_ingestion_runs"
    assert {"dataset_id", "source_id", "workbook_name", "sheet_name", "source_row"}.issubset(
        entry.c.keys()
    )
    assert {"processing_status", "reason_code", "file_sha256"}.issubset(entry.c.keys())
    assert {"legal_document_id", "document_version_id"}.issubset(entry.c.keys())
    assert {"dataset_id", "mode", "status", "summary", "finished_at"}.issubset(run.c.keys())
    assert any(
        constraint.name == "uq_corpus_catalog_entries_source_row"
        for constraint in entry.constraints
    )
