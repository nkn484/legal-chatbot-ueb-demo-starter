"""Source-neutral orchestration for immutable legal document ingestion."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from legal_chatbot.core.logging import get_logger
from legal_chatbot.ingestion.config import IngestionSettings
from legal_chatbot.ingestion.embedding import EmbeddingPort
from legal_chatbot.ingestion.models import (
    ChunkDraft,
    EmbeddingKind,
    IngestionResult,
    NormalizedDocument,
)
from legal_chatbot.sources.models import FetchApprovedDocumentRef, LegalDocumentSnapshot
from legal_chatbot.sources.port import LegalSourcePort


class NormalizerPort(Protocol):
    """Boundary for deterministic HTML normalization."""

    def normalize(self, html: str) -> NormalizedDocument:
        """Normalize raw HTML into its canonical representation."""
        ...


class ChunkerPort(Protocol):
    """Boundary for deterministic normalized-document chunking."""

    def chunk(self, document: NormalizedDocument) -> tuple[ChunkDraft, ...]:
        """Create bounded drafts from canonical document text."""
        ...


class DocumentRepositoryPort(Protocol):
    """Transactional persistence boundary owned by the documents module."""

    async def find_existing(
        self,
        source_id: str,
        external_id: str,
        snapshot_sha256: str,
        *,
        block_count: int,
        embedding_model_id: str,
    ) -> IngestionResult | None:
        """Return a fully materialized immutable version when it is already stored."""
        ...

    async def persist(
        self,
        snapshot: LegalDocumentSnapshot,
        normalized: NormalizedDocument,
        chunks: Sequence[ChunkDraft],
        vectors: Sequence[Sequence[float]],
        *,
        snapshot_sha256: str,
        embedding_model_id: str,
        embedding_kind: EmbeddingKind,
    ) -> IngestionResult:
        """Atomically persist one complete immutable version and its vectors."""
        ...


def _utc_iso(value: datetime | None) -> str | None:
    """Serialize an optional aware datetime as a canonical UTC ISO-8601 value."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("snapshot datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_snapshot_sha256(
    snapshot: LegalDocumentSnapshot,
    normalized: NormalizedDocument,
    settings: IngestionSettings,
) -> str:
    """Hash stable evidence plus the profile that produced its persisted representation.

    ``retrieved_at`` intentionally records observation time only. It must not create a
    new immutable legal version when all source evidence and ingestion profile are otherwise
    identical. Batch size affects only processing throughput, so it is intentionally excluded.
    """
    metadata = {
        "source_id": snapshot.source_id,
        "external_id": snapshot.external_id,
        "document_number": snapshot.document_number,
        "title": snapshot.title,
        "document_type": snapshot.document_type,
        "issuing_authority": snapshot.issuing_authority,
        "issue_date": _utc_iso(snapshot.issue_date),
        "effective_date": _utc_iso(snapshot.effective_date),
        "source_updated_at": _utc_iso(snapshot.source_updated_at),
        "legal_status": snapshot.legal_status,
        "canonical_url": snapshot.canonical_url,
        "normalizer_version": normalized.normalizer_version,
    }
    trust_mode = snapshot.provenance.transport_trust_mode
    assert trust_mode is not None
    provenance = {
        "provenance_type": snapshot.provenance.provenance_type.value,
        "source_id": snapshot.provenance.source_id,
        "transport": snapshot.provenance.transport,
        "operation": snapshot.provenance.operation,
        "canonical_url": snapshot.provenance.canonical_url,
        "tls_verified": snapshot.provenance.tls_verified,
        "transport_trust_mode": trust_mode.value,
        "tls_chain_verified": snapshot.provenance.tls_chain_verified,
        "tls_hostname_verified": snapshot.provenance.tls_hostname_verified,
        "trust_exception_id": snapshot.provenance.trust_exception_id,
        "trust_exception_digest": snapshot.provenance.trust_exception_digest,
        "policy_id": snapshot.provenance.policy_id,
        "policy_version": snapshot.provenance.policy_version,
        "compiled_policy_digest": snapshot.provenance.compiled_policy_digest,
        "registry_snapshot_digest": snapshot.provenance.registry_snapshot_digest,
        "pin_set_id": snapshot.provenance.pin_set_id,
        "pin_set_version": snapshot.provenance.pin_set_version,
        "pin_set_digest": snapshot.provenance.pin_set_digest,
        "matched_pin_id": snapshot.provenance.matched_pin_id,
        "peer_certificate_not_before": _utc_iso(snapshot.provenance.peer_certificate_not_before),
        "peer_certificate_not_after": _utc_iso(snapshot.provenance.peer_certificate_not_after),
        "acquisition_correlation_id": snapshot.provenance.acquisition_correlation_id,
    }
    canonical = {
        "ingestion_profile": {
            "normalizer_version": settings.html_normalizer_version,
            "chunker_version": settings.legal_block_version,
            "chunk_max_chars": settings.chunk_max_chars,
            "chunk_overlap_chars": settings.chunk_overlap_chars,
            "embedding_model_id": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "embedding_kind": EmbeddingKind.DEMO_NON_SEMANTIC.value,
        },
        "metadata": metadata,
        "normalized_text_sha256": normalized.sha256,
        "provenance": provenance,
        "source_content_sha256": snapshot.content_sha256,
    }
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _safe_source_id(value: str) -> str:
    """Limit log labels to a harmless, compact operational identifier."""
    normalized = value.strip().upper()
    if (
        not normalized
        or len(normalized) > 32
        or not normalized.isascii()
        or not normalized.isalnum()
    ):
        return "unknown"
    return normalized


class IngestionService:
    """Fetch, deduplicate, embed, and transactionally persist legal snapshots."""

    def __init__(
        self,
        repository: DocumentRepositoryPort,
        normalizer: NormalizerPort,
        chunker: ChunkerPort,
        embedder: EmbeddingPort,
        settings: IngestionSettings,
    ) -> None:
        self._repository = repository
        self._normalizer = normalizer
        self._chunker = chunker
        self._embedder = embedder
        self._settings = settings
        self._logger = get_logger()

    async def ingest(
        self, source: LegalSourcePort, ref: FetchApprovedDocumentRef
    ) -> IngestionResult:
        """Fetch only a manifest-derived capability, then ingest its returned snapshot."""
        if not isinstance(ref, FetchApprovedDocumentRef):
            raise TypeError("ingestion requires a fetch-approved document reference")
        try:
            snapshot = await source.fetch_document(ref)
        except Exception:
            # A source failure has no document identity yet. Do not log exception text.
            self._log_failure(ref.source_id)
            raise
        return await self.ingest_snapshot(snapshot)

    async def ingest_snapshot(self, snapshot: LegalDocumentSnapshot) -> IngestionResult:
        """Ingest one snapshot, embedding only after an immutable-version lookup."""
        source_id = _safe_source_id(snapshot.source_id)
        try:
            raw_html_sha256 = sha256(snapshot.content_html.encode("utf-8")).hexdigest()
            if raw_html_sha256 != snapshot.content_sha256:
                raise ValueError("snapshot content hash does not match raw HTML")

            normalized = self._normalizer.normalize(snapshot.content_html)
            snapshot_sha256 = canonical_snapshot_sha256(snapshot, normalized, self._settings)
            existing = await self._repository.find_existing(
                snapshot.source_id,
                snapshot.external_id,
                snapshot_sha256,
                block_count=len(normalized.blocks),
                embedding_model_id=self._settings.embedding_model,
            )
            if existing is not None:
                self._log_complete(source_id, existing)
                return existing

            chunks = self._chunker.chunk(normalized)
            if not chunks:
                raise ValueError("chunker returned no chunks")
            vectors, embedding_kind = await self._embed_chunks(chunks)
            result = await self._repository.persist(
                snapshot,
                normalized,
                chunks,
                vectors,
                snapshot_sha256=snapshot_sha256,
                embedding_model_id=self._settings.embedding_model,
                embedding_kind=embedding_kind,
            )
            self._log_complete(source_id, result)
            return result
        except Exception:
            # Persistence owns one transaction; all pre-persistence work is validated above.
            self._log_failure(source_id)
            raise

    async def _embed_chunks(
        self, chunks: Sequence[ChunkDraft]
    ) -> tuple[tuple[tuple[float, ...], ...], EmbeddingKind]:
        """Embed drafts in bounded batches and validate the complete vector alignment."""
        vectors: list[tuple[float, ...]] = []
        embedding_kind: EmbeddingKind | None = None
        for start in range(0, len(chunks), self._settings.embedding_batch_size):
            batch_chunks = chunks[start : start + self._settings.embedding_batch_size]
            batch = await self._embedder.embed(tuple(chunk.text for chunk in batch_chunks))
            if batch.model_id != self._settings.embedding_model:
                raise ValueError("embedding model does not match ingestion settings")
            if batch.dimension != self._settings.embedding_dimension:
                raise ValueError("embedding dimension does not match ingestion settings")
            if len(batch.vectors) != len(batch_chunks):
                raise ValueError("embedding vector count does not match chunk batch")
            if embedding_kind is None:
                embedding_kind = batch.embedding_kind
            elif batch.embedding_kind != embedding_kind:
                raise ValueError("embedding kind changed between batches")
            vectors.extend(batch.vectors)

        if len(vectors) != len(chunks) or embedding_kind is None:
            raise ValueError("embedding vector count does not match chunks")
        if any(len(vector) != self._settings.embedding_dimension for vector in vectors):
            raise ValueError("embedding vector dimension does not match ingestion settings")
        return tuple(vectors), embedding_kind

    def _log_complete(self, source_id: str, result: IngestionResult) -> None:
        self._logger.info(
            "ingestion_complete",
            extra={
                "source": source_id,
                "document_id": str(result.document_id),
                "document_version_id": str(result.document_version_id),
                "ingestion_outcome": result.outcome.value,
                "chunk_count": result.chunk_count,
                "embedding_count": result.embedding_count,
                "embedding_model_id": result.embedding_model_id,
                "semantic_ready": result.semantic_ready,
            },
        )

    def _log_failure(self, source_id: str) -> None:
        self._logger.error(
            "ingestion_failure",
            extra={
                "source": _safe_source_id(source_id),
                "ingestion_outcome": "failed",
                "embedding_model_id": self._settings.embedding_model,
            },
        )
