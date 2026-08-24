"""Metadata-only checks for the document ingestion persistence schema."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import CHAR, CheckConstraint, Computed, Double, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

from legal_chatbot.db.base import Base
from legal_chatbot.documents.orm import (
    ChunkEmbedding,
    CitationRecord,
    RetrievalRun,
    SourceProvenanceRecord,
    _tls_chain_verified_default,
    _tls_hostname_verified_default,
    _transport_trust_mode_default,
)


def test_document_tables_are_registered_on_base_metadata() -> None:
    expected_tables = {
        "legal_documents",
        "source_provenance_records",
        "document_versions",
        "document_chunks",
        "chunk_embeddings",
        "retrieval_runs",
        "citation_records",
    }
    assert expected_tables <= set(Base.metadata.tables)


class _InsertDefaultContext:
    def __init__(self, tls_verified: bool) -> None:
        self._parameters = {"tls_verified": tls_verified}

    def get_current_parameters(self) -> dict[str, bool]:
        return self._parameters


def test_legacy_orm_insert_defaults_are_row_local_and_do_not_infer_tofu() -> None:
    strict_context = _InsertDefaultContext(True)
    legacy_context = _InsertDefaultContext(False)

    assert (
        _transport_trust_mode_default(strict_context),
        _tls_chain_verified_default(strict_context),
        _tls_hostname_verified_default(strict_context),
    ) == ("STRICT_TLS", True, True)
    assert (
        _transport_trust_mode_default(legacy_context),
        _tls_chain_verified_default(legacy_context),
        _tls_hostname_verified_default(legacy_context),
    ) == ("LEGACY_UNVERIFIED", False, False)
    assert SourceProvenanceRecord.__table__.c.transport_trust_mode.default is not None
    assert SourceProvenanceRecord.__table__.c.tls_chain_verified.default is not None
    assert SourceProvenanceRecord.__table__.c.tls_hostname_verified.default is not None


def test_document_identity_version_and_chunk_constraints_are_declared() -> None:
    document = Base.metadata.tables["legal_documents"]
    provenance = SourceProvenanceRecord.__table__
    version = Base.metadata.tables["document_versions"]
    chunk = Base.metadata.tables["document_chunks"]

    assert isinstance(document.c.id.type, UUID)
    assert any(
        set(constraint.columns.keys()) == {"source_id", "external_id"}
        for constraint in document.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert set(version.columns.keys()) == {
        "id",
        "document_id",
        "version_number",
        "document_number",
        "document_number_normalized",
        "title",
        "title_search_vector",
        "document_type",
        "issuing_authority",
        "issue_date",
        "effective_date",
        "source_updated_at",
        "legal_status",
        "canonical_url",
        "raw_html",
        "normalized_text",
        "snapshot_sha256",
        "source_content_sha256",
        "normalized_text_sha256",
        "normalizer_version",
        "normalized_block_count",
        "created_at",
    }
    assert any(
        set(constraint.columns.keys()) == {"document_id", "version_number"}
        for constraint in version.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert any(
        set(constraint.columns.keys()) == {"document_id", "snapshot_sha256"}
        for constraint in version.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert {
        constraint.sqltext.text
        for constraint in version.constraints
        if isinstance(constraint, CheckConstraint)
    } >= {
        "version_number > 0",
        "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
        "source_content_sha256 ~ '^[0-9a-f]{64}$'",
        "normalized_text_sha256 ~ '^[0-9a-f]{64}$'",
        "normalized_block_count >= 1",
    }
    assert isinstance(version.c.snapshot_sha256.type, CHAR)
    assert isinstance(version.c.source_content_sha256.type, CHAR)
    assert isinstance(version.c.normalized_text_sha256.type, CHAR)
    assert version.c.document_number_normalized.nullable
    assert version.c.document_number_normalized.type.length == 256
    assert isinstance(version.c.title_search_vector.type, TSVECTOR)
    assert isinstance(version.c.title_search_vector.computed, Computed)
    assert version.c.title_search_vector.computed.sqltext.text == (
        "to_tsvector('pg_catalog.simple', coalesce(title, ''))"
    )
    assert version.c.title_search_vector.computed.persisted is True
    assert {index.name for index in version.indexes} >= {
        "ix_document_versions_document_number_normalized",
        "ix_document_versions_title_search_vector_gin",
    }
    assert any(
        set(constraint.columns.keys()) == {"document_version_id", "ordinal"}
        for constraint in chunk.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert set(chunk.columns.keys()) == {
        "id",
        "document_version_id",
        "ordinal",
        "content_text",
        "search_vector",
        "start_char",
        "end_char",
        "content_sha256",
        "chunker_version",
        "locator",
        "created_at",
    }
    check_expressions = {
        constraint.sqltext.text
        for constraint in chunk.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert check_expressions >= {
        "start_char >= 0",
        "end_char > start_char",
        "content_sha256 ~ '^[0-9a-f]{64}$'",
    }
    assert isinstance(chunk.c.locator.type, JSONB)
    assert chunk.c.locator.nullable
    assert isinstance(chunk.c.content_sha256.type, CHAR)
    assert isinstance(chunk.c.search_vector.type, TSVECTOR)
    assert isinstance(chunk.c.search_vector.computed, Computed)
    assert chunk.c.search_vector.computed.sqltext.text == (
        "to_tsvector('pg_catalog.simple', content_text)"
    )
    assert chunk.c.search_vector.computed.persisted is True
    search_vector_index = next(
        index for index in chunk.indexes if index.name == "ix_document_chunks_search_vector_gin"
    )
    assert list(search_vector_index.columns.keys()) == ["search_vector"]
    assert search_vector_index.dialect_options["postgresql"]["using"] == "gin"
    assert {
        "transport_trust_mode",
        "tls_chain_verified",
        "tls_hostname_verified",
        "trust_exception_id",
        "trust_exception_digest",
        "policy_id",
        "policy_version",
        "compiled_policy_digest",
        "registry_snapshot_digest",
        "pin_set_id",
        "pin_set_version",
        "pin_set_digest",
        "matched_pin_id",
        "peer_certificate_not_before",
        "peer_certificate_not_after",
        "acquisition_correlation_id",
    } <= set(provenance.columns.keys())
    provenance_checks = {
        constraint.name
        for constraint in provenance.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_source_provenance_records_transport_trust_mode",
        "ck_source_provenance_records_tls_verified_compatibility",
        "ck_source_provenance_records_policy_metadata_shape",
        "ck_source_provenance_records_trust_identity_format",
        "ck_source_provenance_records_transport_trust_shape",
    } <= provenance_checks
    assert {index.name for index in provenance.indexes} >= {
        "ix_source_provenance_records_trust_mode",
        "ix_source_provenance_records_policy_identity",
    }


def test_embedding_vector_and_hnsw_cosine_index_are_declared() -> None:
    embedding_table = ChunkEmbedding.__table__
    embedding = embedding_table.c.embedding
    hnsw_index = next(
        index
        for index in embedding_table.indexes
        if index.name == "ix_chunk_embeddings_embedding_hnsw_cosine"
    )

    assert isinstance(embedding.type, Vector)
    assert embedding.type.dim == 384
    assert set(embedding_table.columns.keys()) == {
        "id",
        "document_chunk_id",
        "embedding",
        "embedding_model_id",
        "embedding_kind",
        "dimension",
        "embedding_input_sha256",
        "created_at",
    }
    assert any(
        set(constraint.columns.keys()) == {"document_chunk_id", "embedding_model_id"}
        for constraint in embedding_table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert isinstance(embedding_table.c.embedding_input_sha256.type, CHAR)
    assert hnsw_index.dialect_options["postgresql"]["using"] == "hnsw"
    assert hnsw_index.dialect_options["postgresql"]["with"] == {"m": 16, "ef_construction": 64}
    assert hnsw_index.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}
    assert list(hnsw_index.columns.keys()) == ["embedding"]
    assert {index.name for index in embedding_table.indexes} == {
        "ix_chunk_embeddings_document_chunk_id",
        "ix_chunk_embeddings_embedding_hnsw_cosine",
    }


def test_retrieval_run_and_citation_metadata_preserve_evidence() -> None:
    retrieval_run = RetrievalRun.__table__
    citation = CitationRecord.__table__

    assert set(retrieval_run.columns.keys()) == {
        "id",
        "strategy",
        "strategy_version",
        "scope",
        "trust_scope",
        "query_max_chars",
        "top_k",
        "candidate_count",
        "citation_count",
        "evidence_decision",
        "evidence_reason",
        "created_at",
    }
    assert retrieval_run.c.evidence_reason.type.length == 128
    assert retrieval_run.c.trust_scope.server_default is not None
    retrieval_checks = {
        constraint.sqltext.text
        for constraint in retrieval_run.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert retrieval_checks >= {
        "scope = 'LATEST_INGESTED'",
        "query_max_chars BETWEEN 1 AND 4000",
        "top_k BETWEEN 1 AND 20",
        "candidate_count >= 0",
        "citation_count >= 0",
        "citation_count <= candidate_count",
        "evidence_decision IN ('EVIDENCE_AVAILABLE', 'NO_RESULTS', "
        "'UNSUPPORTED_TEMPORAL_SCOPE', 'INVALID_EVIDENCE_CHAIN')",
    }
    assert {index.name for index in retrieval_run.indexes} == {
        "ix_retrieval_runs_created_at",
        "ix_retrieval_runs_trust_scope",
    }

    assert set(citation.columns.keys()) == {
        "id",
        "retrieval_run_id",
        "document_chunk_id",
        "source_provenance_record_id",
        "rank",
        "lexical_score",
        "semantic_score",
        "reranker_score",
        "created_at",
    }
    assert isinstance(citation.c.lexical_score.type, Double)
    assert citation.c.lexical_score.nullable
    assert isinstance(citation.c.semantic_score.type, Double)
    assert citation.c.semantic_score.nullable
    assert isinstance(citation.c.reranker_score.type, Double)
    assert citation.c.reranker_score.nullable
    assert any(
        set(constraint.columns.keys()) == {"retrieval_run_id", "rank"}
        for constraint in citation.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    assert any(
        set(constraint.columns.keys()) == {"retrieval_run_id", "document_chunk_id"}
        for constraint in citation.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    citation_checks = {
        constraint.sqltext.text
        for constraint in citation.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "rank > 0" in citation_checks
    assert any("lexical_score IS NULL OR" in expression for expression in citation_checks)
    assert "lexical_score IS NOT NULL OR semantic_score IS NOT NULL" in citation_checks
    assert any("reranker_score IS NULL OR" in expression for expression in citation_checks)
    foreign_key_ondelete = {
        foreign_key.parent.name: foreign_key.ondelete for foreign_key in citation.foreign_keys
    }
    assert foreign_key_ondelete == {
        "retrieval_run_id": "RESTRICT",
        "document_chunk_id": "RESTRICT",
        "source_provenance_record_id": "RESTRICT",
    }
    assert {index.name for index in citation.indexes} == {
        "ix_citation_records_retrieval_run_id",
        "ix_citation_records_document_chunk_id",
        "ix_citation_records_source_provenance_record_id",
    }
    for relationship_name in (
        "retrieval_run",
        "document_chunk",
        "source_provenance_record",
    ):
        cascade = getattr(CitationRecord, relationship_name).property.cascade
        assert "delete" not in cascade
        assert "delete-orphan" not in cascade
