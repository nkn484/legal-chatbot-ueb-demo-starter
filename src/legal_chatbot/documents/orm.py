"""SQLAlchemy persistence schema for immutable source document evidence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from legal_chatbot.db.base import Base


def _legacy_tls_value(context: Any) -> bool:
    """Read the row-local legacy compatibility flag for an insert default."""

    tls_verified = context.get_current_parameters().get("tls_verified")
    if not isinstance(tls_verified, bool):
        raise ValueError("tls_verified must be explicitly set for trust compatibility defaults")
    return tls_verified


def _transport_trust_mode_default(context: Any) -> str:
    """Backfill direct legacy ORM inserts without inferring a TOFU exception."""

    return "STRICT_TLS" if _legacy_tls_value(context) else "LEGACY_UNVERIFIED"


def _tls_chain_verified_default(context: Any) -> bool:
    return _legacy_tls_value(context)


def _tls_hostname_verified_default(context: Any) -> bool:
    return _legacy_tls_value(context)


class LegalDocument(Base):
    """Stable identity for one document in one source system."""

    __tablename__ = "legal_documents"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_legal_documents_source_external"),
        Index("ix_legal_documents_source_id", "source_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document")


class CorpusIngestionRun(Base):
    """Auditable bounded execution of one manual corpus import."""

    __tablename__ = "corpus_ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'COMPLETED_WITH_FAILURES', 'FAILED')",
            name="ck_corpus_ingestion_runs_status",
        ),
        Index("ix_corpus_ingestion_runs_dataset_started", "dataset_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RUNNING")
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CorpusCatalogEntry(Base):
    """One workbook row, including rows that cannot yet become retrieval evidence."""

    __tablename__ = "corpus_catalog_entries"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "source_id",
            "workbook_name",
            "sheet_name",
            "source_row",
            name="uq_corpus_catalog_entries_source_row",
        ),
        CheckConstraint(
            "source_id IN ('VBQPPL', 'VNU', 'UEB')",
            name="ck_corpus_catalog_entries_source_id",
        ),
        CheckConstraint(
            "file_kind IN ('DIRECT_FILE', 'FOLDER', 'MISSING', 'UNRESOLVED')",
            name="ck_corpus_catalog_entries_file_kind",
        ),
        CheckConstraint(
            "processing_status IN ('DISCOVERED', 'FILE_PENDING', 'FILE_DOWNLOADED', "
            "'EXTRACTED', 'OCR_REQUIRED', 'CHUNKED', 'INDEXED', 'QUARANTINED', 'FAILED')",
            name="ck_corpus_catalog_entries_processing_status",
        ),
        CheckConstraint("source_row >= 2", name="ck_corpus_catalog_entries_source_row_positive"),
        CheckConstraint(
            "record_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_corpus_catalog_entries_record_sha256",
        ),
        CheckConstraint(
            "file_sha256 IS NULL OR file_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_corpus_catalog_entries_file_sha256",
        ),
        Index("ix_corpus_catalog_entries_dataset_source", "dataset_id", "source_id"),
        Index("ix_corpus_catalog_entries_status", "processing_status"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    workbook_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sheet_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_row: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(String(256), nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(4096))
    document_type: Mapped[str | None] = mapped_column(String(512))
    issuing_authority: Mapped[str | None] = mapped_column(String(1024))
    issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_status: Mapped[str | None] = mapped_column(String(256))
    file_label: Mapped[str | None] = mapped_column(String(2048))
    file_url: Mapped[str | None] = mapped_column(String(2048))
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    record_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(128))
    file_sha256: Mapped[str | None] = mapped_column(CHAR(64))
    legal_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("legal_documents.id", ondelete="SET NULL")
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SourceProvenanceRecord(Base):
    """Immutable record of how a particular document version was retrieved."""

    __tablename__ = "source_provenance_records"
    __table_args__ = (
        Index("ix_source_provenance_records_version_id", "document_version_id"),
        Index("ix_source_provenance_records_source_retrieved_at", "source_id", "retrieved_at"),
        Index("ix_source_provenance_records_trust_mode", "transport_trust_mode"),
        Index("ix_source_provenance_records_policy_identity", "policy_id", "policy_version"),
        CheckConstraint(
            "transport_trust_mode IN "
            "('STRICT_TLS', 'USER_APPROVED_TOFU_PINNED_EXCEPTION', 'LEGACY_UNVERIFIED')",
            name="ck_source_provenance_records_transport_trust_mode",
        ),
        CheckConstraint(
            "tls_verified = (tls_chain_verified AND tls_hostname_verified)",
            name="ck_source_provenance_records_tls_verified_compatibility",
        ),
        CheckConstraint(
            "(policy_id IS NULL AND policy_version IS NULL AND compiled_policy_digest IS NULL "
            "AND registry_snapshot_digest IS NULL) OR "
            "(policy_id IS NOT NULL AND policy_version IS NOT NULL "
            "AND compiled_policy_digest IS NOT NULL AND registry_snapshot_digest IS NOT NULL)",
            name="ck_source_provenance_records_policy_metadata_shape",
        ),
        CheckConstraint(
            "(trust_exception_id IS NULL OR trust_exception_id ~ "
            "'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
            "AND (policy_id IS NULL OR policy_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
            "AND (pin_set_id IS NULL OR pin_set_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
            "AND (matched_pin_id IS NULL OR matched_pin_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
            "AND (acquisition_correlation_id IS NULL OR "
            "acquisition_correlation_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
            "AND (policy_version IS NULL OR policy_version > 0) "
            "AND (pin_set_version IS NULL OR pin_set_version > 0)",
            name="ck_source_provenance_records_trust_identity_format",
        ),
        CheckConstraint(
            "(transport_trust_mode = 'STRICT_TLS' "
            "AND tls_chain_verified AND tls_hostname_verified AND tls_verified "
            "AND trust_exception_id IS NULL AND trust_exception_digest IS NULL "
            "AND pin_set_id IS NULL AND pin_set_version IS NULL AND pin_set_digest IS NULL "
            "AND matched_pin_id IS NULL AND peer_certificate_not_before IS NULL "
            "AND peer_certificate_not_after IS NULL) OR "
            "(transport_trust_mode = 'USER_APPROVED_TOFU_PINNED_EXCEPTION' "
            "AND tls_chain_verified AND NOT tls_hostname_verified AND NOT tls_verified "
            "AND trust_exception_id IS NOT NULL AND trust_exception_digest IS NOT NULL "
            "AND policy_id IS NOT NULL AND policy_version IS NOT NULL "
            "AND compiled_policy_digest IS NOT NULL AND registry_snapshot_digest IS NOT NULL "
            "AND pin_set_id IS NOT NULL AND pin_set_version IS NOT NULL "
            "AND pin_set_digest IS NOT NULL "
            "AND matched_pin_id IS NOT NULL AND peer_certificate_not_before IS NOT NULL "
            "AND peer_certificate_not_after IS NOT NULL "
            "AND peer_certificate_not_before <= peer_certificate_not_after "
            "AND acquisition_correlation_id IS NOT NULL) OR "
            "(transport_trust_mode = 'LEGACY_UNVERIFIED' "
            "AND NOT tls_chain_verified AND NOT tls_hostname_verified AND NOT tls_verified "
            "AND trust_exception_id IS NULL AND trust_exception_digest IS NULL "
            "AND policy_id IS NULL AND policy_version IS NULL AND compiled_policy_digest IS NULL "
            "AND registry_snapshot_digest IS NULL AND pin_set_id IS NULL "
            "AND pin_set_version IS NULL "
            "AND pin_set_digest IS NULL AND matched_pin_id IS NULL "
            "AND peer_certificate_not_before IS NULL AND peer_certificate_not_after IS NULL "
            "AND acquisition_correlation_id IS NULL)",
            name="ck_source_provenance_records_transport_trust_shape",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    provenance_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False)
    transport: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(128), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    tls_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    transport_trust_mode: Mapped[str] = mapped_column(
        String(48), default=_transport_trust_mode_default, nullable=False
    )
    tls_chain_verified: Mapped[bool] = mapped_column(
        Boolean, default=_tls_chain_verified_default, nullable=False
    )
    tls_hostname_verified: Mapped[bool] = mapped_column(
        Boolean, default=_tls_hostname_verified_default, nullable=False
    )
    trust_exception_id: Mapped[str | None] = mapped_column(String(128))
    trust_exception_digest: Mapped[str | None] = mapped_column(CHAR(64))
    policy_id: Mapped[str | None] = mapped_column(String(128))
    policy_version: Mapped[int | None] = mapped_column(Integer)
    compiled_policy_digest: Mapped[str | None] = mapped_column(CHAR(64))
    registry_snapshot_digest: Mapped[str | None] = mapped_column(CHAR(64))
    pin_set_id: Mapped[str | None] = mapped_column(String(128))
    pin_set_version: Mapped[int | None] = mapped_column(Integer)
    pin_set_digest: Mapped[str | None] = mapped_column(CHAR(64))
    matched_pin_id: Mapped[str | None] = mapped_column(String(128))
    peer_certificate_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    peer_certificate_not_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acquisition_correlation_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="provenance_records")
    citation_records: Mapped[list[CitationRecord]] = relationship(
        back_populates="source_provenance_record"
    )


class DocumentVersion(Base):
    """An immutable normalized snapshot of a legal document."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id", "version_number", name="uq_document_versions_document_version_number"
        ),
        UniqueConstraint(
            "document_id", "snapshot_sha256", name="uq_document_versions_document_snapshot"
        ),
        CheckConstraint("version_number > 0", name="ck_document_versions_version_number_positive"),
        CheckConstraint(
            "normalized_block_count >= 1",
            name="ck_document_versions_normalized_block_count_positive",
        ),
        CheckConstraint(
            "snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_versions_snapshot_sha256"
        ),
        CheckConstraint(
            "source_content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_source_content_sha256",
        ),
        CheckConstraint(
            "normalized_text_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_document_versions_normalized_text_sha256",
        ),
        Index("ix_document_versions_document_id", "document_id"),
        Index("ix_document_versions_source_updated_at", "source_updated_at"),
        Index("ix_document_versions_document_number_normalized", "document_number_normalized"),
        Index(
            "ix_document_versions_title_search_vector_gin",
            "title_search_vector",
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("legal_documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    document_number: Mapped[str | None] = mapped_column(String(256))
    document_number_normalized: Mapped[str | None] = mapped_column(String(256))
    title: Mapped[str | None] = mapped_column(String(4096))
    title_search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('pg_catalog.simple', coalesce(title, ''))", persisted=True),
        nullable=False,
    )
    document_type: Mapped[str | None] = mapped_column(String(512))
    issuing_authority: Mapped[str | None] = mapped_column(String(1024))
    issue_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    legal_status: Mapped[str | None] = mapped_column(String(256))
    canonical_url: Mapped[str | None] = mapped_column(String(2048))
    raw_html: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    source_content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    normalized_text_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_block_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[LegalDocument] = relationship(back_populates="versions")
    provenance_records: Mapped[list[SourceProvenanceRecord]] = relationship(
        back_populates="document_version"
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document_version")


class DocumentChunk(Base):
    """A locator-addressable text range from an immutable document version."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "ordinal", name="uq_document_chunks_version_ordinal"
        ),
        CheckConstraint("ordinal >= 0", name="ck_document_chunks_ordinal_nonnegative"),
        CheckConstraint("start_char >= 0", name="ck_document_chunks_start_char_nonnegative"),
        CheckConstraint("end_char > start_char", name="ck_document_chunks_chars_ordered"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_chunks_content_sha256"
        ),
        Index("ix_document_chunks_document_version_id", "document_version_id"),
        Index("ix_document_chunks_search_vector_gin", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('pg_catalog.simple', content_text)", persisted=True),
        nullable=False,
    )
    start_char: Mapped[int] = mapped_column(Integer, nullable=False)
    end_char: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(64), nullable=False)
    locator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(back_populates="chunk")
    citation_records: Mapped[list[CitationRecord]] = relationship(back_populates="document_chunk")


class ChunkEmbedding(Base):
    """A model-specific vector representation of one document chunk."""

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "document_chunk_id",
            "embedding_model_id",
            name="uq_chunk_embeddings_chunk_model_id",
        ),
        CheckConstraint("dimension = 384", name="ck_chunk_embeddings_dimension_384"),
        CheckConstraint(
            "embedding_input_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_chunk_embeddings_embedding_input_sha256",
        ),
        Index("ix_chunk_embeddings_document_chunk_id", "document_chunk_id"),
        Index(
            "ix_chunk_embeddings_embedding_hnsw_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    document_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)
    embedding_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    embedding_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=384)
    embedding_input_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunk: Mapped[DocumentChunk] = relationship(back_populates="embeddings")


class RetrievalRun(Base):
    """An immutable record of the bounded lexical retrieval policy that was applied."""

    __tablename__ = "retrieval_runs"
    __table_args__ = (
        CheckConstraint(
            "scope = 'LATEST_INGESTED'", name="ck_retrieval_runs_scope_latest_ingested"
        ),
        CheckConstraint(
            "query_max_chars BETWEEN 1 AND 4000",
            name="ck_retrieval_runs_query_max_chars_range",
        ),
        CheckConstraint("top_k BETWEEN 1 AND 20", name="ck_retrieval_runs_top_k_range"),
        CheckConstraint(
            "candidate_count >= 0", name="ck_retrieval_runs_candidate_count_nonnegative"
        ),
        CheckConstraint("citation_count >= 0", name="ck_retrieval_runs_citation_count_nonnegative"),
        CheckConstraint(
            "citation_count <= candidate_count",
            name="ck_retrieval_runs_citation_count_within_candidates",
        ),
        CheckConstraint(
            "evidence_decision IN "
            "('EVIDENCE_AVAILABLE', 'NO_RESULTS', 'UNSUPPORTED_TEMPORAL_SCOPE', "
            "'INVALID_EVIDENCE_CHAIN')",
            name="ck_retrieval_runs_evidence_decision",
        ),
        Index("ix_retrieval_runs_created_at", "created_at"),
        Index("ix_retrieval_runs_trust_scope", "trust_scope"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    trust_scope: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'STRICT_TLS_ONLY'")
    )
    query_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_decision: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_reason: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    citation_records: Mapped[list[CitationRecord]] = relationship(back_populates="retrieval_run")


class CitationRecord(Base):
    """Immutable evidence selected for one retrieval run."""

    __tablename__ = "citation_records"
    __table_args__ = (
        UniqueConstraint("retrieval_run_id", "rank", name="uq_citation_records_run_rank"),
        UniqueConstraint(
            "retrieval_run_id", "document_chunk_id", name="uq_citation_records_run_chunk"
        ),
        CheckConstraint("rank > 0", name="ck_citation_records_rank_positive"),
        CheckConstraint(
            "lexical_score IS NULL OR (lexical_score >= 0 "
            "AND lexical_score <> 'NaN'::double precision "
            "AND lexical_score <> 'Infinity'::double precision "
            "AND lexical_score <> '-Infinity'::double precision)",
            name="ck_citation_records_lexical_score_finite_nonnegative",
        ),
        CheckConstraint(
            "semantic_score IS NULL OR (semantic_score BETWEEN -1 AND 1 "
            "AND semantic_score <> 'NaN'::double precision "
            "AND semantic_score <> 'Infinity'::double precision "
            "AND semantic_score <> '-Infinity'::double precision)",
            name="ck_citation_records_semantic_score_finite_range",
        ),
        CheckConstraint(
            "lexical_score IS NOT NULL OR semantic_score IS NOT NULL",
            name="ck_citation_records_at_least_one_score",
        ),
        CheckConstraint(
            "reranker_score IS NULL OR (reranker_score <> 'NaN'::double precision "
            "AND reranker_score <> 'Infinity'::double precision "
            "AND reranker_score <> '-Infinity'::double precision)",
            name="ck_citation_records_reranker_score_finite",
        ),
        Index("ix_citation_records_retrieval_run_id", "retrieval_run_id"),
        Index("ix_citation_records_document_chunk_id", "document_chunk_id"),
        Index("ix_citation_records_source_provenance_record_id", "source_provenance_record_id"),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)
    retrieval_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_runs.id", ondelete="RESTRICT"), nullable=False
    )
    document_chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="RESTRICT"), nullable=False
    )
    source_provenance_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_provenance_records.id", ondelete="RESTRICT"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    lexical_score: Mapped[float | None] = mapped_column(Double)
    semantic_score: Mapped[float | None] = mapped_column(Double)
    reranker_score: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    retrieval_run: Mapped[RetrievalRun] = relationship(back_populates="citation_records")
    document_chunk: Mapped[DocumentChunk] = relationship(back_populates="citation_records")
    source_provenance_record: Mapped[SourceProvenanceRecord] = relationship(
        back_populates="citation_records"
    )


class ReviewedLegalEffectImport(Base):
    """An approved, shadow-only import of reviewed legal-effect assertions."""

    __tablename__ = "reviewed_legal_effect_imports"
    __table_args__ = (
        UniqueConstraint(
            "artifact_sha256", name="uq_reviewed_legal_effect_imports_artifact_sha256"
        ),
        CheckConstraint(
            "artifact_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_reviewed_legal_effect_imports_artifact_sha256",
        ),
        CheckConstraint(
            "reviewer_role = 'LEGAL_REVIEWER'",
            name="ck_reviewed_legal_effect_imports_reviewer_role",
        ),
        CheckConstraint(
            "approver_role = 'LEGAL_APPROVER'",
            name="ck_reviewed_legal_effect_imports_approver_role",
        ),
        CheckConstraint(
            "runtime_enabled = false",
            name="ck_reviewed_legal_effect_imports_runtime_disabled",
        ),
        CheckConstraint(
            "submitted_at <= reviewed_at AND reviewed_at <= approved_at "
            "AND approved_at <= imported_at",
            name="ck_reviewed_legal_effect_imports_timestamp_order",
        ),
    )

    import_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    artifact_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(128), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reviewer_role: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(32), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    imported_by: Mapped[str] = mapped_column(String(128), nullable=False)
    runtime_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


class ReviewedLegalEffectFamily(Base):
    """A declared completeness boundary within one reviewed-effect import."""

    __tablename__ = "reviewed_legal_effect_families"
    __table_args__ = (
        CheckConstraint(
            "completeness IN ('DECLARED_PARTIAL', 'DECLARED_COMPLETE')",
            name="ck_reviewed_legal_effect_families_completeness",
        ),
        CheckConstraint(
            "btrim(scope_note) <> '' AND scope_note !~ '[[:cntrl:]]'",
            name="ck_reviewed_legal_effect_families_scope_note_valid",
        ),
    )

    import_id: Mapped[str] = mapped_column(
        ForeignKey("reviewed_legal_effect_imports.import_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    family_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    completeness: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_note: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewedLegalEffectAssertion(Base):
    """One reviewed relation, anchored only to immutable document evidence."""

    __tablename__ = "reviewed_legal_effect_assertions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["import_id", "family_id"],
            [
                "reviewed_legal_effect_families.import_id",
                "reviewed_legal_effect_families.family_id",
            ],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "subject_document_version_id <> object_document_version_id",
            name="ck_reviewed_legal_effect_assertions_distinct_endpoints",
        ),
        CheckConstraint(
            "relation_kind IN ('IMPLEMENTS', 'GOVERNS')",
            name="ck_reviewed_legal_effect_assertions_relation_kind",
        ),
        CheckConstraint(
            "effect_state = 'EFFECT_NOT_MODELED'",
            name="ck_reviewed_legal_effect_assertions_effect_state",
        ),
        CheckConstraint(
            "basis_locator_type IN ('ARTICLE', 'CLAUSE', 'SECTION', 'PAGE')",
            name="ck_reviewed_legal_effect_assertions_basis_locator_type",
        ),
        CheckConstraint(
            "btrim(basis_locator_value) <> ''",
            name="ck_reviewed_legal_effect_assertions_basis_locator_value",
        ),
        CheckConstraint(
            "reviewed_at <= approved_at AND approved_at <= created_at",
            name="ck_reviewed_legal_effect_assertions_timestamp_order",
        ),
        Index(
            "ix_reviewed_legal_effect_assertions_subject_version",
            "subject_document_version_id",
        ),
        Index(
            "ix_reviewed_legal_effect_assertions_object_version",
            "object_document_version_id",
        ),
        Index("ix_reviewed_legal_effect_assertions_family", "import_id", "family_id"),
        Index("ix_reviewed_legal_effect_assertions_relation_kind", "relation_kind"),
        Index(
            "ix_reviewed_legal_effect_assertions_basis_provenance",
            "basis_source_provenance_record_id",
        ),
    )

    assertion_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    import_id: Mapped[str] = mapped_column(String(128), nullable=False)
    family_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    object_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    relation_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    effect_state: Mapped[str] = mapped_column(String(32), nullable=False)
    basis_document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="RESTRICT"), nullable=False
    )
    basis_source_provenance_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("source_provenance_records.id", ondelete="RESTRICT"), nullable=False
    )
    basis_locator_type: Mapped[str] = mapped_column(String(16), nullable=False)
    basis_locator_value: Mapped[str] = mapped_column(String(500), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReviewedLegalEffectEvent(Base):
    """An append-only correction or revocation of a reviewed-effect assertion."""

    __tablename__ = "reviewed_legal_effect_events"
    __table_args__ = (
        CheckConstraint(
            "event_kind IN ('CORRECTS', 'REVOKES')",
            name="ck_reviewed_legal_effect_events_event_kind",
        ),
        CheckConstraint(
            "reason_code IN ('ENDPOINT_NOT_FOUND', 'VERSION_HASH_MISMATCH', "
            "'PROVENANCE_NOT_FOUND', 'LOCATOR_INVALID', 'DUPLICATE_ASSERTION', "
            "'FAMILY_SCOPE_CONFLICT', 'REVIEW_DISAGREEMENT', "
            "'SUPERSEDED_BY_REVIEW', 'WITHDRAWN_BY_REVIEW')",
            name="ck_reviewed_legal_effect_events_reason_code",
        ),
        CheckConstraint(
            "(event_kind = 'CORRECTS' AND successor_assertion_id IS NOT NULL) OR "
            "(event_kind = 'REVOKES' AND successor_assertion_id IS NULL)",
            name="ck_reviewed_legal_effect_events_successor_shape",
        ),
        CheckConstraint(
            "successor_assertion_id IS NULL OR successor_assertion_id <> assertion_id",
            name="ck_reviewed_legal_effect_events_successor_not_self",
        ),
        CheckConstraint(
            "reviewed_at <= approved_at AND approved_at <= created_at",
            name="ck_reviewed_legal_effect_events_timestamp_order",
        ),
        Index("ix_reviewed_legal_effect_events_assertion", "assertion_id"),
        Index("ix_reviewed_legal_effect_events_successor", "successor_assertion_id"),
        Index("ix_reviewed_legal_effect_events_event_kind", "event_kind"),
    )

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    assertion_id: Mapped[str] = mapped_column(
        ForeignKey("reviewed_legal_effect_assertions.assertion_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    successor_assertion_id: Mapped[str | None] = mapped_column(
        ForeignKey("reviewed_legal_effect_assertions.assertion_id", ondelete="RESTRICT")
    )
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_note: Mapped[str] = mapped_column(String(500), nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
