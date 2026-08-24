"""Unit coverage for source-neutral M04 ingestion orchestration."""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from legal_chatbot.core.logging import configure_logging
from legal_chatbot.ingestion import (
    ChunkDraft,
    EmbeddingBatch,
    EmbeddingKind,
    HTMLNormalizer,
    IngestionOutcome,
    IngestionResult,
    IngestionService,
    IngestionSettings,
    canonical_snapshot_sha256,
)
from legal_chatbot.sources.models import (
    DiscoveryCandidate,
    FetchApprovedDocumentRef,
    LegalDocumentSnapshot,
    ProvenanceType,
    SourceDocumentRef,
    SourceProvenance,
    TransportTrustMode,
)


def _snapshot(
    *,
    html: str = "<p>alpha legal text</p>",
    title: str = "Title",
    retrieved_at: datetime | None = None,
) -> LegalDocumentSnapshot:
    return LegalDocumentSnapshot(
        source_id="VBQPPL",
        external_id="allowed-1",
        title=title,
        content_html=html,
        content_sha256=sha256(html.encode("utf-8")).hexdigest(),
        provenance=SourceProvenance(
            provenance_type=ProvenanceType.SOURCE_FETCH,
            source_id="VBQPPL",
            transport="rest",
            operation="get_document",
            retrieved_at=retrieved_at or datetime(2026, 1, 1, tzinfo=UTC),
            tls_verified=True,
        ),
    )


def _result(outcome: IngestionOutcome = IngestionOutcome.CREATED) -> IngestionResult:
    return IngestionResult(
        document_id=uuid4(),
        document_version_id=uuid4(),
        version_number=1,
        outcome=outcome,
        block_count=1,
        chunk_count=1,
        embedding_count=1,
    )


class FakeRepository:
    def __init__(self, existing: IngestionResult | None = None) -> None:
        self.existing = existing
        self.find_calls: list[dict[str, object]] = []
        self.persist_calls: list[dict[str, object]] = []

    async def find_existing(self, *args: object, **kwargs: object) -> IngestionResult | None:
        self.find_calls.append({"args": args, **kwargs})
        return self.existing

    async def persist(self, *args: object, **kwargs: object) -> IngestionResult:
        self.persist_calls.append({"args": args, **kwargs})
        return _result()


class FailingRepository(FakeRepository):
    async def persist(self, *args: object, **kwargs: object) -> IngestionResult:
        self.persist_calls.append({"args": args, **kwargs})
        raise RuntimeError("repository transaction failed")


class FakeChunker:
    def __init__(self, count: int = 1) -> None:
        self.count = count
        self.calls = 0

    def chunk(self, _document: object) -> tuple[ChunkDraft, ...]:
        self.calls += 1
        return tuple(
            ChunkDraft(
                ordinal=ordinal,
                start=0,
                end=len(f"word {ordinal}"),
                text=f"word {ordinal}",
                content_sha256=sha256(f"word {ordinal}".encode()).hexdigest(),
                chunker_version="legal-block-v1",
            )
            for ordinal in range(self.count)
        )


class FakeEmbedder:
    def __init__(self, *, mismatch: bool = False) -> None:
        self.mismatch = mismatch
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts: tuple[str, ...]) -> EmbeddingBatch | SimpleNamespace:
        self.calls.append(texts)
        vector_count = len(texts) - 1 if self.mismatch else len(texts)
        if self.mismatch:
            return SimpleNamespace(
                model_id="local-hash-v1",
                dimension=384,
                embedding_kind=EmbeddingKind.DEMO_NON_SEMANTIC,
                vectors=tuple((1.0,) * 384 for _ in range(vector_count)),
            )
        return EmbeddingBatch(vectors=tuple((1.0,) * 384 for _ in range(vector_count)))


class FakeSource:
    def __init__(self, snapshot: LegalDocumentSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    async def fetch_document(self, _ref: FetchApprovedDocumentRef) -> LegalDocumentSnapshot:
        self.calls += 1
        return self.snapshot


def _service(
    repository: FakeRepository,
    *,
    chunk_count: int = 1,
    mismatch: bool = False,
) -> tuple[IngestionService, FakeChunker, FakeEmbedder]:
    settings = IngestionSettings()
    chunker = FakeChunker(chunk_count)
    embedder = FakeEmbedder(mismatch=mismatch)
    service = IngestionService(repository, HTMLNormalizer(), chunker, embedder, settings)
    return service, chunker, embedder


def _fetch_ref() -> FetchApprovedDocumentRef:
    return FetchApprovedDocumentRef(
        source_id="VBQPPL",
        external_id="allowed-1",
        document_number="test/1",
        canonical_url="https://vbpl.vn/test/1",
        transport="SOAP",
        detail_path="/test/1",
        operation="GetVanBanById",
    )


def test_snapshot_hash_binds_stable_evidence_and_ingestion_profile() -> None:
    normalizer = HTMLNormalizer()
    settings = IngestionSettings()
    baseline = _snapshot()
    later = _snapshot(retrieved_at=baseline.provenance.retrieved_at + timedelta(days=1))
    changed_title = _snapshot(title="Changed")
    changed_content = _snapshot(html="<p>different legal text</p>")
    different_batch_size = IngestionSettings(INGESTION_EMBEDDING_BATCH_SIZE=2)
    different_chunk_max = IngestionSettings(INGESTION_CHUNK_MAX_CHARS=1_300)
    different_overlap = IngestionSettings(INGESTION_CHUNK_OVERLAP_CHARS=300)
    # Model and dimension are deliberately profile-only copies: production settings remain literal.
    different_model = settings.model_copy(update={"embedding_model": "test-profile-model"})
    different_dimension = settings.model_copy(update={"embedding_dimension": 768})

    baseline_hash = canonical_snapshot_sha256(
        baseline, normalizer.normalize(baseline.content_html), settings
    )
    later_hash = canonical_snapshot_sha256(
        later, normalizer.normalize(later.content_html), settings
    )
    assert baseline_hash == later_hash
    assert baseline_hash == canonical_snapshot_sha256(
        baseline, normalizer.normalize(baseline.content_html), different_batch_size
    )
    assert baseline_hash != canonical_snapshot_sha256(
        baseline, normalizer.normalize(baseline.content_html), different_chunk_max
    )
    assert baseline_hash != canonical_snapshot_sha256(
        baseline, normalizer.normalize(baseline.content_html), different_overlap
    )
    assert baseline_hash != canonical_snapshot_sha256(
        baseline, normalizer.normalize(baseline.content_html), different_model
    )
    assert baseline_hash != canonical_snapshot_sha256(
        baseline, normalizer.normalize(baseline.content_html), different_dimension
    )
    assert baseline_hash != canonical_snapshot_sha256(
        changed_title, normalizer.normalize(changed_title.content_html), settings
    )
    assert baseline_hash != canonical_snapshot_sha256(
        changed_content, normalizer.normalize(changed_content.content_html), settings
    )
    trust_digest = sha256(b"trust-identity").hexdigest()
    tofu_snapshot = baseline.model_copy(
        update={
            "provenance": SourceProvenance(
                provenance_type=ProvenanceType.SOURCE_FETCH,
                source_id="VBQPPL",
                transport="rest",
                operation="get_document",
                retrieved_at=baseline.provenance.retrieved_at,
                tls_verified=False,
                transport_trust_mode=TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION,
                tls_chain_verified=True,
                tls_hostname_verified=False,
                trust_exception_id="vbqppl-tofu-2026",
                trust_exception_digest=trust_digest,
                policy_id="vbqppl-policy-1",
                policy_version=1,
                compiled_policy_digest=trust_digest,
                registry_snapshot_digest=trust_digest,
                pin_set_id="vbqppl-pins-2026",
                pin_set_version=1,
                pin_set_digest=trust_digest,
                matched_pin_id="ws-vbpl-spki-1",
                peer_certificate_not_before=datetime(2026, 6, 10, tzinfo=UTC),
                peer_certificate_not_after=datetime(2026, 12, 26, tzinfo=UTC),
                acquisition_correlation_id="acquisition-20260821-1",
            )
        }
    )
    assert baseline_hash != canonical_snapshot_sha256(
        tofu_snapshot, normalizer.normalize(tofu_snapshot.content_html), settings
    )


@pytest.mark.asyncio
async def test_ingest_fetches_through_source_port_and_skips_identical_before_embedding() -> None:
    existing = _result(IngestionOutcome.UNCHANGED)
    repository = FakeRepository(existing)
    service, chunker, embedder = _service(repository)
    source = FakeSource(_snapshot())
    result = await service.ingest(source, _fetch_ref())

    assert result == existing
    assert source.calls == 1
    assert len(repository.find_calls) == 1
    assert chunker.calls == 0
    assert embedder.calls == []
    assert repository.persist_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref",
    [
        SourceDocumentRef(source_id="VBQPPL", external_id="allowed-1"),
        DiscoveryCandidate(
            source_id="VBQPPL",
            document_number="test/1",
            external_id="allowed-1",
            transport="SOAP",
        ),
    ],
)
async def test_ingest_rejects_non_fetch_capabilities_before_source_call(ref: object) -> None:
    source = FakeSource(_snapshot())
    service, _chunker, _embedder = _service(FakeRepository())

    with pytest.raises(TypeError, match="fetch-approved"):
        await service.ingest(source, ref)  # type: ignore[arg-type]

    assert source.calls == 0


@pytest.mark.asyncio
async def test_ingest_batches_embeddings_and_persists_aligned_vectors() -> None:
    repository = FakeRepository()
    service, _chunker, embedder = _service(repository, chunk_count=33)

    await service.ingest_snapshot(_snapshot())

    assert [len(batch) for batch in embedder.calls] == [32, 1]
    assert len(repository.persist_calls) == 1
    persisted_vectors = repository.persist_calls[0]["args"][3]
    assert len(persisted_vectors) == 33


@pytest.mark.asyncio
async def test_embedding_mismatch_fails_before_persistence() -> None:
    repository = FakeRepository()
    service, _chunker, _embedder = _service(repository, mismatch=True)

    with pytest.raises(ValueError, match="embedding vector count"):
        await service.ingest_snapshot(_snapshot())

    assert repository.persist_calls == []


@pytest.mark.asyncio
async def test_failure_logs_are_sanitized_and_never_include_content() -> None:
    stream = io.StringIO()
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    try:
        configure_logging("INFO", stream=stream)
        bad_html = "<p>PRIVATE-LEGAL-CONTENT</p>"
        snapshot = _snapshot(html=bad_html).model_copy(update={"content_sha256": "0" * 64})
        service, _chunker, _embedder = _service(FakeRepository())

        with pytest.raises(ValueError, match="content hash"):
            await service.ingest_snapshot(snapshot)

        payload = json.loads(stream.getvalue().splitlines()[-1])
        assert payload["message"] == "ingestion_failure"
        assert payload["ingestion_outcome"] == "failed"
        assert "PRIVATE-LEGAL-CONTENT" not in stream.getvalue()
    finally:
        root.handlers[:] = original_handlers


@pytest.mark.asyncio
async def test_repository_failure_propagates_without_a_result() -> None:
    repository = FailingRepository()
    service, _chunker, _embedder = _service(repository)

    with pytest.raises(RuntimeError, match="repository transaction failed"):
        await service.ingest_snapshot(_snapshot())

    assert len(repository.persist_calls) == 1
