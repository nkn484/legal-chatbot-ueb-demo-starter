"""LegalSourcePort adapter for reviewed workbook rows and their linked PDF snapshots."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from time import monotonic

import httpx

from legal_chatbot.demo_corpus.config import DemoCorpusSettings
from legal_chatbot.demo_corpus.models import CatalogEntry, CorpusFileKind, DownloadedAsset
from legal_chatbot.demo_corpus.pdf import PDFTextExtractor, render_extracted_html
from legal_chatbot.demo_corpus.workbook import direct_download_url
from legal_chatbot.sources.models import (
    FetchApprovedDocumentRef,
    LegalDocumentSnapshot,
    ProvenanceType,
    SourceHealth,
    SourceHealthStatus,
    SourceProvenance,
)


class ManualSnapshotSourceAdapter:
    """Fetch only immutable references derived from the loaded workbook catalog."""

    def __init__(
        self,
        source_id: str,
        entries: tuple[CatalogEntry, ...],
        settings: DemoCorpusSettings,
        extractor: PDFTextExtractor,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._source_id = source_id
        self._settings = settings
        self._extractor = extractor
        self._entries = {
            entry.external_id: entry
            for entry in entries
            if entry.source_id == source_id and entry.file_kind is CorpusFileKind.DIRECT_FILE
        }
        self._client = client or httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.response_timeout_seconds,
                write=settings.response_timeout_seconds,
                pool=settings.connect_timeout_seconds,
            ),
        )
        self._owns_client = client is None

    async def list_documents(self) -> tuple[FetchApprovedDocumentRef, ...]:
        return tuple(self._ref(entry) for entry in self._entries.values())

    async def fetch_document(self, ref: FetchApprovedDocumentRef) -> LegalDocumentSnapshot:
        snapshot, _asset = await self.fetch_document_artifact(ref)
        return snapshot

    async def fetch_document_artifact(
        self, ref: FetchApprovedDocumentRef
    ) -> tuple[LegalDocumentSnapshot, DownloadedAsset]:
        entry = self._validate_ref(ref)
        assert entry.file_url is not None
        url = direct_download_url(entry.file_url)
        if url is None:
            raise ValueError("snapshot_url_not_downloadable")
        asset = await self._download(url)
        extracted = await asyncio.to_thread(self._extractor.extract, asset.content)
        content_html = render_extracted_html(extracted)
        now = datetime.now(UTC)
        snapshot = LegalDocumentSnapshot(
            source_id=entry.source_id,
            external_id=entry.external_id,
            document_number=entry.document_number,
            title=entry.title,
            document_type=entry.document_type,
            issuing_authority=entry.issuing_authority,
            issue_date=entry.issue_date,
            effective_date=entry.effective_date,
            source_updated_at=None,
            legal_status=entry.legal_status,
            canonical_url=entry.file_url,
            content_html=content_html,
            content_sha256=sha256(content_html.encode("utf-8")).hexdigest(),
            provenance=SourceProvenance(
                provenance_type=ProvenanceType.MANUAL_SNAPSHOT,
                source_id=entry.source_id,
                transport="GOOGLE_DRIVE_MANUAL_SNAPSHOT",
                operation="download_reviewed_snapshot",
                retrieved_at=now,
                canonical_url=entry.file_url,
                tls_verified=True,
            ),
        )
        return snapshot, asset

    async def health_check(self) -> SourceHealth:
        started = monotonic()
        return SourceHealth(
            status=SourceHealthStatus.HEALTHY,
            source_id=self._source_id,
            transport="GOOGLE_DRIVE_MANUAL_SNAPSHOT",
            duration_ms=(monotonic() - started) * 1_000,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _ref(self, entry: CatalogEntry) -> FetchApprovedDocumentRef:
        return FetchApprovedDocumentRef(
            source_id=entry.source_id,
            external_id=entry.external_id,
            document_number=entry.document_number,
            canonical_url=entry.file_url,
            transport="GOOGLE_DRIVE_MANUAL_SNAPSHOT",
            detail_path=f"/demo-corpus/{entry.sheet_name}/{entry.source_row}",
            operation="READ_MANUAL_SNAPSHOT",
        )

    def _validate_ref(self, ref: FetchApprovedDocumentRef) -> CatalogEntry:
        entry = self._entries.get(ref.external_id)
        if (
            entry is None
            or ref.source_id != self._source_id
            or ref.transport != "GOOGLE_DRIVE_MANUAL_SNAPSHOT"
            or ref.operation != "READ_MANUAL_SNAPSHOT"
            or ref.document_number != entry.document_number
            or ref.canonical_url != entry.file_url
            or ref.detail_path != f"/demo-corpus/{entry.sheet_name}/{entry.source_row}"
        ):
            raise ValueError("snapshot_reference_not_approved")
        return entry

    async def _download(self, url: str) -> DownloadedAsset:
        content = bytearray()
        async with self._client.stream(
            "GET", url, headers={"Accept": "application/pdf"}
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > self._settings.max_response_bytes:
                    raise ValueError("snapshot_file_too_large")
                content.extend(chunk)
        value = bytes(content)
        if not value.startswith(b"%PDF"):
            raise ValueError("snapshot_asset_is_not_pdf")
        return DownloadedAsset(
            content=value,
            sha256=sha256(value).hexdigest(),
            content_type="application/pdf",
        )
