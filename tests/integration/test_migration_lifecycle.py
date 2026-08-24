"""Opt-in lifecycle coverage for M04/M05/M07/M08 and reviewed-effect migrations."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import URL, make_url

from legal_chatbot.core.config import Settings

pytestmark = pytest.mark.integration

if os.getenv("RUN_INTEGRATION") != "1" or os.getenv("RUN_MIGRATION_LIFECYCLE") != "1":
    pytest.skip(
        "set RUN_INTEGRATION=1 and RUN_MIGRATION_LIFECYCLE=1 to run migration lifecycle checks",
        allow_module_level=True,
    )

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_M04_TABLES = {
    "legal_documents",
    "source_provenance_records",
    "document_versions",
    "document_chunks",
    "chunk_embeddings",
}
_M05_TABLES = {"retrieval_runs", "citation_records"}
_M07_TABLES = {
    "conversations",
    "conversation_exchanges",
    "conversation_exchange_references",
}
_M08_TABLES = {
    "channel_conversation_bindings",
    "channel_outbound_deliveries",
}
_CORPUS_TABLES = {"corpus_ingestion_runs", "corpus_catalog_entries"}
_REVIEWED_EFFECT_TABLES = {
    "reviewed_legal_effect_imports",
    "reviewed_legal_effect_families",
    "reviewed_legal_effect_assertions",
    "reviewed_legal_effect_events",
}
_HNSW_INDEX = "ix_chunk_embeddings_embedding_hnsw_cosine"
_SEARCH_VECTOR_INDEX = "ix_document_chunks_search_vector_gin"


def _database_name() -> str:
    return f"m08_lifecycle_{uuid4().hex}"


async def _connect(url: URL, database: str) -> asyncpg.Connection:
    """Open an asyncpg connection without rendering or logging the URL."""

    if url.host is None or url.username is None or url.password is None:
        raise RuntimeError("DATABASE_URL must include host, user, and password")
    return await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=database,
    )


async def _drop_database(connection: asyncpg.Connection, database_name: str) -> None:
    """Terminate temporary database sessions before dropping the generated database."""

    await connection.execute(
        "SELECT pg_terminate_backend(pid) "
        "FROM pg_stat_activity "
        "WHERE datname = $1 AND pid <> pg_backend_pid()",
        database_name,
    )
    await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')


def _run_alembic(arguments: list[str], database_url: str) -> None:
    """Run Alembic without exposing command output or database credentials on failure."""

    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, "Alembic migration lifecycle command failed"


async def _table_names(connection: asyncpg.Connection, tables: set[str]) -> set[str]:
    rows = await connection.fetch(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' AND tablename = ANY($1::text[])",
        list(tables),
    )
    return {row["tablename"] for row in rows}


async def _assert_vector_and_m04_m05_schema(connection: asyncpg.Connection) -> None:
    assert await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
    )
    assert await _table_names(connection, _M04_TABLES | _M05_TABLES) == _M04_TABLES | _M05_TABLES
    assert await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1)",
        _HNSW_INDEX,
    )
    assert await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1)",
        _SEARCH_VECTOR_INDEX,
    )
    assert await connection.fetchval(
        "SELECT attgenerated = 's' "
        "FROM pg_attribute "
        "WHERE attrelid = 'document_chunks'::regclass AND attname = 'search_vector'"
    )


async def _assert_m07_schema(connection: asyncpg.Connection) -> None:
    assert await _table_names(connection, _M07_TABLES) == _M07_TABLES

    conversation_constraints = {
        row["conname"]: row["definition"]
        for row in await connection.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid = 'conversations'::regclass"
        )
    }
    assert conversation_constraints["pk_conversations"] == "PRIMARY KEY (id)"
    assert {
        "ck_conversations_state_version_nonnegative",
        "ck_conversations_expires_after_created",
    } <= set(conversation_constraints)

    exchange_constraints = {
        row["conname"]: row["definition"]
        for row in await connection.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid = 'conversation_exchanges'::regclass"
        )
    }
    assert exchange_constraints["pk_conversation_exchanges"] == "PRIMARY KEY (id)"
    assert {
        "uq_conversation_exchanges_conversation_delivery_key_sha256",
        "uq_conversation_exchanges_conversation_ordinal",
        "ck_conversation_exchanges_delivery_key_sha256",
        "ck_conversation_exchanges_ordinal_positive",
        "ck_conversation_exchanges_status",
        "ck_conversation_exchanges_user_text_length",
        "ck_conversation_exchanges_assistant_text_length",
        "ck_conversation_exchanges_chat_outcome",
        "ck_conversation_exchanges_status_shape",
        "ck_conversation_exchanges_completed_result_shape",
        "ck_conversation_exchanges_failure_reason",
    } <= set(exchange_constraints)
    status_shape = exchange_constraints["ck_conversation_exchanges_status_shape"]
    assert "PROCESSING" in status_shape
    assert "retrieval_run_id IS NULL" in status_shape
    assert "provider IS NULL" in status_shape
    assert "model IS NULL" in status_shape
    assert "request_id IS NULL" in status_shape
    completed_result_shape = exchange_constraints[
        "ck_conversation_exchanges_completed_result_shape"
    ]
    assert "ANSWER_GROUNDED" in completed_result_shape
    assert "NO_RESULTS" in completed_result_shape
    assert "RETRIEVAL_FAILURE" in completed_result_shape
    assert "CITATION_REVALIDATION_FAILURE" in completed_result_shape
    assert "retrieval_run_id IS NOT NULL" in completed_result_shape
    assert "PROCESSING_FAILED" in exchange_constraints["ck_conversation_exchanges_failure_reason"]

    exchange_foreign_keys = {
        row["definition"]
        for row in await connection.fetch(
            "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = 'conversation_exchanges'::regclass AND contype = 'f'"
        )
    }
    assert any(
        "REFERENCES conversations(id) ON DELETE CASCADE" in definition
        for definition in exchange_foreign_keys
    )
    assert any(
        "REFERENCES retrieval_runs(id) ON DELETE RESTRICT" in definition
        for definition in exchange_foreign_keys
    )

    processing_index = await connection.fetchrow(
        "SELECT index_relation.indisunique AS is_unique, "
        "pg_get_expr(index_relation.indpred, index_relation.indrelid) AS predicate "
        "FROM pg_index index_relation "
        "JOIN pg_class index_class ON index_class.oid = index_relation.indexrelid "
        "WHERE index_relation.indrelid = 'conversation_exchanges'::regclass "
        "AND index_class.relname = 'uq_conversation_exchanges_processing_conversation'"
    )
    assert processing_index is not None
    assert processing_index["is_unique"] is True
    assert "status" in processing_index["predicate"]
    assert "PROCESSING" in processing_index["predicate"]

    reference_constraints = {
        row["conname"]: row["definition"]
        for row in await connection.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = 'conversation_exchange_references'::regclass"
        )
    }
    assert reference_constraints["pk_conversation_exchange_references"] == (
        "PRIMARY KEY (exchange_id, kind, ordinal)"
    )
    assert "uq_conversation_exchange_references_exchange_kind_reference" in reference_constraints
    assert {
        "ck_conversation_exchange_references_kind",
        "ck_conversation_exchange_references_ordinal_range",
    } <= set(reference_constraints)
    reference_foreign_key = await connection.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = 'conversation_exchange_references'::regclass AND contype = 'f'"
    )
    assert reference_foreign_key == (
        "FOREIGN KEY (exchange_id) REFERENCES conversation_exchanges(id) ON DELETE CASCADE"
    )


async def _assert_m08_schema(connection: asyncpg.Connection) -> None:
    assert await _table_names(connection, _M08_TABLES) == _M08_TABLES

    binding_constraints = {
        row["conname"]: row["definition"]
        for row in await connection.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid = 'channel_conversation_bindings'::regclass"
        )
    }
    assert binding_constraints["pk_channel_conversation_bindings"] == "PRIMARY KEY (id)"
    assert {
        "uq_channel_conversation_bindings_channel_identity_hmac",
        "ck_channel_conversation_bindings_channel_kind",
        "ck_channel_conversation_bindings_identity_hmac",
        "ck_channel_conversation_bindings_safe_error_code",
        "ck_channel_conversation_bindings_status",
        "ck_channel_conversation_bindings_status_shape",
    } <= set(binding_constraints)
    assert binding_constraints["ck_channel_conversation_bindings_channel_kind"] == (
        "CHECK (((channel_kind)::text = 'ZALO_OFFICIAL_BOT'::text))"
    )
    assert "BINDING" in binding_constraints["ck_channel_conversation_bindings_status_shape"]
    assert "ACTIVE" in binding_constraints["ck_channel_conversation_bindings_status_shape"]
    assert "FAILED" in binding_constraints["ck_channel_conversation_bindings_status_shape"]
    binding_safe_error_constraint = binding_constraints[
        "ck_channel_conversation_bindings_safe_error_code"
    ]
    assert "safe_error_code IS NULL" in binding_safe_error_constraint
    assert "^[A-Z][A-Z0-9_]{0,63}$" in binding_safe_error_constraint
    binding_foreign_keys = {
        row["definition"]
        for row in await connection.fetch(
            "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = 'channel_conversation_bindings'::regclass AND contype = 'f'"
        )
    }
    assert binding_foreign_keys == {
        "FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE"
    }

    active_binding_index = await connection.fetchrow(
        "SELECT index_relation.indisunique AS is_unique, "
        "pg_get_expr(index_relation.indpred, index_relation.indrelid) AS predicate "
        "FROM pg_index index_relation "
        "JOIN pg_class index_class ON index_class.oid = index_relation.indexrelid "
        "WHERE index_relation.indrelid = 'channel_conversation_bindings'::regclass "
        "AND index_class.relname = 'uq_channel_conversation_bindings_active_conversation'"
    )
    assert active_binding_index is not None
    assert active_binding_index["is_unique"] is True
    assert "status" in active_binding_index["predicate"]
    assert "ACTIVE" in active_binding_index["predicate"]

    delivery_constraints = {
        row["conname"]: row["definition"]
        for row in await connection.fetch(
            "SELECT conname, pg_get_constraintdef(oid) AS definition "
            "FROM pg_constraint WHERE conrelid = 'channel_outbound_deliveries'::regclass"
        )
    }
    assert delivery_constraints["pk_channel_outbound_deliveries"] == "PRIMARY KEY (id)"
    assert {
        "uq_channel_outbound_deliveries_channel_binding_exchange",
        "uq_channel_outbound_deliveries_channel_delivery_hmac",
        "ck_channel_outbound_deliveries_channel_kind",
        "ck_channel_outbound_deliveries_delivery_hmac",
        "ck_channel_outbound_deliveries_safe_error_code",
        "ck_channel_outbound_deliveries_status",
        "ck_channel_outbound_deliveries_attempt_count_range",
        "ck_channel_outbound_deliveries_status_shape",
    } <= set(delivery_constraints)
    assert delivery_constraints["ck_channel_outbound_deliveries_channel_kind"] == (
        "CHECK (((channel_kind)::text = 'ZALO_OFFICIAL_BOT'::text))"
    )
    assert "ABANDONED" in delivery_constraints["ck_channel_outbound_deliveries_status_shape"]
    assert "attempt_count" in delivery_constraints["ck_channel_outbound_deliveries_status_shape"]
    delivery_safe_error_constraint = delivery_constraints[
        "ck_channel_outbound_deliveries_safe_error_code"
    ]
    assert "safe_error_code IS NULL" in delivery_safe_error_constraint
    assert "^[A-Z][A-Z0-9_]{0,63}$" in delivery_safe_error_constraint
    delivery_foreign_keys = {
        row["definition"]
        for row in await connection.fetch(
            "SELECT pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = 'channel_outbound_deliveries'::regclass AND contype = 'f'"
        )
    }
    assert delivery_foreign_keys == {
        "FOREIGN KEY (binding_id) REFERENCES channel_conversation_bindings(id) ON DELETE CASCADE",
        "FOREIGN KEY (exchange_id) REFERENCES conversation_exchanges(id) ON DELETE CASCADE",
    }

    sending_delivery_index = await connection.fetchrow(
        "SELECT index_relation.indisunique AS is_unique, "
        "pg_get_expr(index_relation.indpred, index_relation.indrelid) AS predicate "
        "FROM pg_index index_relation "
        "JOIN pg_class index_class ON index_class.oid = index_relation.indexrelid "
        "WHERE index_relation.indrelid = 'channel_outbound_deliveries'::regclass "
        "AND index_class.relname = 'uq_channel_outbound_deliveries_sending_binding'"
    )
    assert sending_delivery_index is not None
    assert sending_delivery_index["is_unique"] is True
    assert "status" in sending_delivery_index["predicate"]
    assert "SENDING" in sending_delivery_index["predicate"]


async def _assert_reviewed_legal_effect_registry_schema(connection: asyncpg.Connection) -> None:
    assert await _table_names(connection, _REVIEWED_EFFECT_TABLES) == _REVIEWED_EFFECT_TABLES
    assertion_constraints = {
        row["conname"]
        for row in await connection.fetch(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'reviewed_legal_effect_assertions'::regclass"
        )
    }
    assert {
        "ck_reviewed_legal_effect_assertions_relation_kind",
        "ck_reviewed_legal_effect_assertions_effect_state",
        "ck_reviewed_legal_effect_assertions_basis_locator_type",
        "ck_reviewed_legal_effect_assertions_distinct_endpoints",
    } <= assertion_constraints
    event_constraints = {
        row["conname"]
        for row in await connection.fetch(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'reviewed_legal_effect_events'::regclass"
        )
    }
    assert {
        "ck_reviewed_legal_effect_events_event_kind",
        "ck_reviewed_legal_effect_events_reason_code",
        "ck_reviewed_legal_effect_events_successor_shape",
        "ck_reviewed_legal_effect_events_successor_not_self",
    } <= event_constraints
    trigger_names = {
        row["tgname"]
        for row in await connection.fetch(
            "SELECT trigger_info.tgname FROM pg_trigger AS trigger_info "
            "JOIN pg_class AS relation ON relation.oid = trigger_info.tgrelid "
            "WHERE relation.relname = ANY($1::text[]) AND NOT trigger_info.tgisinternal",
            list(_REVIEWED_EFFECT_TABLES),
        )
    }
    assert trigger_names == {
        f"trg_{table_name}_append_only" for table_name in _REVIEWED_EFFECT_TABLES
    }
    assert await connection.fetchval(
        "SELECT to_regprocedure('reviewed_legal_effect_reject_mutation()') IS NOT NULL"
    )


async def _assert_reviewed_legal_effect_registry_guards(connection: asyncpg.Connection) -> None:
    subject_document_id, object_document_id, basis_document_id = uuid4(), uuid4(), uuid4()
    subject_version_id, object_version_id, basis_version_id = uuid4(), uuid4(), uuid4()
    provenance_id = uuid4()
    for document_id, version_id, external_id in (
        (subject_document_id, subject_version_id, "reviewed-effect-subject"),
        (object_document_id, object_version_id, "reviewed-effect-object"),
        (basis_document_id, basis_version_id, "reviewed-effect-basis"),
    ):
        await connection.execute(
            "INSERT INTO legal_documents (id, source_id, external_id) VALUES ($1, 'TEST0012', $2)",
            document_id,
            external_id,
        )
        await connection.execute(
            "INSERT INTO document_versions ("
            "id, document_id, version_number, raw_html, normalized_text, snapshot_sha256, "
            "source_content_sha256, normalized_text_sha256, normalizer_version, "
            "normalized_block_count) VALUES ($1, $2, 1, 'text', 'text', $3, $3, $3, 'test', 1)",
            version_id,
            document_id,
            "a" * 64,
        )
    await connection.execute(
        "INSERT INTO source_provenance_records ("
        "id, document_version_id, provenance_type, source_id, transport, operation, retrieved_at, "
        "tls_verified, transport_trust_mode, tls_chain_verified, tls_hostname_verified) "
        "VALUES ($1, $2, 'manual_snapshot', 'TEST0012', 'TEST', 'registry_guard', now(), "
        "true, 'STRICT_TLS', true, true)",
        provenance_id,
        basis_version_id,
    )
    insert_import = (
        "INSERT INTO reviewed_legal_effect_imports ("
        "import_id, artifact_sha256, schema_version, submitted_by, submitted_at, reviewed_by, "
        "reviewed_at, reviewer_role, approved_by, approved_at, approver_role, imported_by, "
        "runtime_enabled) VALUES ($1, $2, '1', 'submitter', now(), 'reviewer', now(), "
        "'LEGAL_REVIEWER', 'approver', now(), 'LEGAL_APPROVER', 'importer', $3)"
    )
    await connection.execute(insert_import, "import-0012", "b" * 64, False)
    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(insert_import, "duplicate-import-0012", "b" * 64, False)
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(insert_import, "enabled-import-0012", "c" * 64, True)
    await connection.execute(
        "INSERT INTO reviewed_legal_effect_families "
        "(import_id, family_id, completeness, scope_note) VALUES "
        "('import-0012', 'family-0012', 'DECLARED_PARTIAL', 'Synthetic test scope')"
    )
    insert_assertion = (
        "INSERT INTO reviewed_legal_effect_assertions ("
        "assertion_id, import_id, family_id, subject_document_version_id, "
        "object_document_version_id, relation_kind, effect_state, basis_document_version_id, "
        "basis_source_provenance_record_id, basis_locator_type, basis_locator_value, reviewed_by, "
        "reviewed_at, approved_by, approved_at) "
        "VALUES ($1, 'import-0012', 'family-0012', $2, $3, $4, $5, $6, $7, $8, '1', "
        "'reviewer', now(), 'approver', now())"
    )
    invalid_assertion_values = (
        (
            "invalid-relation",
            subject_version_id,
            object_version_id,
            "DEFERRED",
            "EFFECT_NOT_MODELED",
            "ARTICLE",
        ),
        (
            "invalid-effect",
            subject_version_id,
            object_version_id,
            "IMPLEMENTS",
            "DEFERRED",
            "ARTICLE",
        ),
        (
            "invalid-locator",
            subject_version_id,
            object_version_id,
            "IMPLEMENTS",
            "EFFECT_NOT_MODELED",
            "OTHER",
        ),
        (
            "same-endpoint",
            subject_version_id,
            subject_version_id,
            "IMPLEMENTS",
            "EFFECT_NOT_MODELED",
            "ARTICLE",
        ),
    )
    for (
        assertion_id,
        subject_id,
        object_id,
        relation_kind,
        effect_state,
        locator_type,
    ) in invalid_assertion_values:
        with pytest.raises(asyncpg.CheckViolationError):
            await connection.execute(
                insert_assertion,
                assertion_id,
                subject_id,
                object_id,
                relation_kind,
                effect_state,
                basis_version_id,
                provenance_id,
                locator_type,
            )
    await connection.execute(
        insert_assertion,
        "assertion-0012",
        subject_version_id,
        object_version_id,
        "IMPLEMENTS",
        "EFFECT_NOT_MODELED",
        basis_version_id,
        provenance_id,
        "ARTICLE",
    )
    await connection.execute(
        insert_assertion,
        "successor-0012",
        object_version_id,
        basis_version_id,
        "GOVERNS",
        "EFFECT_NOT_MODELED",
        basis_version_id,
        provenance_id,
        "CLAUSE",
    )
    insert_event = (
        "INSERT INTO reviewed_legal_effect_events ("
        "event_id, assertion_id, event_kind, successor_assertion_id, reason_code, reason_note, "
        "reviewed_by, reviewed_at, approved_by, approved_at) VALUES "
        "($1, 'assertion-0012', $2, $3, 'REVIEW_DISAGREEMENT', 'Synthetic test event', "
        "'reviewer', now(), 'approver', now())"
    )
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(insert_event, "invalid-corrects", "CORRECTS", None)
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(insert_event, "invalid-revokes", "REVOKES", "successor-0012")
    await connection.execute(insert_event, "event-0012", "REVOKES", None)
    updates = (
        ("reviewed_legal_effect_imports", "imported_at = imported_at"),
        ("reviewed_legal_effect_families", "scope_note = scope_note"),
        ("reviewed_legal_effect_assertions", "relation_kind = relation_kind"),
        ("reviewed_legal_effect_events", "reason_code = reason_code"),
    )
    for table_name, assignment in updates:
        with pytest.raises(asyncpg.PostgresError) as error:
            await connection.execute(f"UPDATE {table_name} SET {assignment}")
        assert getattr(error.value, "sqlstate", None) == "P0001"


async def _assert_head_schema(connection: asyncpg.Connection) -> None:
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
        "0012_reviewed_legal_effects"
    )
    await _assert_vector_and_m04_m05_schema(connection)
    await _assert_m07_schema(connection)
    await _assert_m08_schema(connection)
    await _assert_reviewed_legal_effect_registry_schema(connection)
    citation_columns = {
        row["attname"]
        for row in await connection.fetch(
            "SELECT attname FROM pg_attribute WHERE attrelid = 'citation_records'::regclass "
            "AND attnum > 0 AND NOT attisdropped"
        )
    }
    assert "reranker_score" in citation_columns
    version_columns = {
        row["attname"]
        for row in await connection.fetch(
            "SELECT attname FROM pg_attribute WHERE attrelid = 'document_versions'::regclass "
            "AND attnum > 0 AND NOT attisdropped"
        )
    }
    assert {"document_number_normalized", "title_search_vector"} <= version_columns
    citation_constraints = {
        row["conname"]
        for row in await connection.fetch(
            "SELECT conname FROM pg_constraint WHERE conrelid = 'citation_records'::regclass"
        )
    }
    assert "ck_citation_records_reranker_score_finite" in citation_constraints
    assert await _table_names(connection, _CORPUS_TABLES) == _CORPUS_TABLES
    provenance_columns = {
        row["attname"]
        for row in await connection.fetch(
            "SELECT attname FROM pg_attribute "
            "WHERE attrelid = 'source_provenance_records'::regclass "
            "AND attnum > 0 AND NOT attisdropped"
        )
    }
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
    } <= provenance_columns
    trust_constraints = {
        row["conname"]
        for row in await connection.fetch(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'source_provenance_records'::regclass"
        )
    }
    assert {
        "ck_source_provenance_records_transport_trust_mode",
        "ck_source_provenance_records_tls_verified_compatibility",
        "ck_source_provenance_records_policy_metadata_shape",
        "ck_source_provenance_records_trust_identity_format",
        "ck_source_provenance_records_transport_trust_shape",
        "ck_source_provenance_records_trust_digests",
    } <= trust_constraints
    assert await connection.fetchval("SELECT trust_scope FROM retrieval_runs LIMIT 1") in {
        None,
        "STRICT_TLS_ONLY",
    }


async def _assert_revision_four_schema(connection: asyncpg.Connection) -> None:
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
        "0004_conversation_state"
    )
    await _assert_vector_and_m04_m05_schema(connection)
    await _assert_m07_schema(connection)
    assert not await _table_names(connection, _M08_TABLES | _CORPUS_TABLES)


async def _assert_revision_three_schema(connection: asyncpg.Connection) -> None:
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
        "0003_retrieval_citation"
    )
    await _assert_vector_and_m04_m05_schema(connection)
    assert not await _table_names(connection, _M07_TABLES | _CORPUS_TABLES)


async def _assert_revision_one_schema(connection: asyncpg.Connection) -> None:
    assert await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
    )
    assert await connection.fetchval("SELECT version_num FROM alembic_version") == (
        "0001_enable_pgvector"
    )
    assert not await _table_names(
        connection, _M04_TABLES | _M05_TABLES | _M07_TABLES | _M08_TABLES | _CORPUS_TABLES
    )
    assert await connection.fetchval("SELECT to_regclass('public.document_chunks') IS NULL")
    assert not await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1)",
        _HNSW_INDEX,
    )
    assert not await connection.fetchval(
        "SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = $1)",
        _SEARCH_VECTOR_INDEX,
    )


@pytest.mark.asyncio
async def test_m08_migration_downgrade_and_upgrade_lifecycle() -> None:
    settings = Settings()  # type: ignore[call-arg]
    source_url = make_url(settings.database_url.get_secret_value())
    temporary_database = _database_name()
    temporary_url = source_url.set(database=temporary_database)
    temporary_database_url = temporary_url.render_as_string(hide_password=False)
    admin_connection = await _connect(source_url, "postgres")

    try:
        await _drop_database(admin_connection, temporary_database)
        await admin_connection.execute(f'CREATE DATABASE "{temporary_database}"')

        _run_alembic(["upgrade", "head"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            await _assert_head_schema(temporary_connection)
            await _assert_reviewed_legal_effect_registry_guards(temporary_connection)
        finally:
            await temporary_connection.close()

        _run_alembic(["downgrade", "0011_document_metadata_search"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            version = await temporary_connection.fetchval("SELECT version_num FROM alembic_version")
            assert version == "0011_document_metadata_search"
            assert not await _table_names(temporary_connection, _REVIEWED_EFFECT_TABLES)
            assert await temporary_connection.fetchval(
                "SELECT to_regprocedure('reviewed_legal_effect_reject_mutation()') IS NULL"
            )
        finally:
            await temporary_connection.close()

        _run_alembic(["upgrade", "head"], temporary_database_url)

        _run_alembic(["downgrade", "0010_reranker_scores"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            version = await temporary_connection.fetchval("SELECT version_num FROM alembic_version")
            assert version == (
                "0010_reranker_scores"
            )
            assert await temporary_connection.fetchval(
                "SELECT to_regclass('public.citation_records') IS NOT NULL"
            )
            assert not await temporary_connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE "
                "attrelid = 'document_versions'::regclass "
                "AND attname = 'document_number_normalized' "
                "AND NOT attisdropped)"
            )
            assert not await temporary_connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE "
                "attrelid = 'document_versions'::regclass AND attname = 'title_search_vector' "
                "AND NOT attisdropped)"
            )
            assert await temporary_connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_attribute WHERE "
                "attrelid = 'citation_records'::regclass AND attname = 'reranker_score' "
                "AND NOT attisdropped)"
            )
        finally:
            await temporary_connection.close()

        _run_alembic(["upgrade", "head"], temporary_database_url)

        _run_alembic(["downgrade", "0005_channel_delivery"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            assert await temporary_connection.fetchval(
                "SELECT version_num FROM alembic_version"
            ) == ("0005_channel_delivery")
            assert await temporary_connection.fetchval(
                "SELECT to_regclass('public.ix_source_provenance_records_trust_mode') IS NULL"
            )
            strict_document_id, strict_version_id, strict_provenance_id = uuid4(), uuid4(), uuid4()
            legacy_document_id, legacy_version_id, legacy_provenance_id = uuid4(), uuid4(), uuid4()
            for document_id, version_id, provenance_id, external_id, tls_verified in (
                (
                    strict_document_id,
                    strict_version_id,
                    strict_provenance_id,
                    "strict-backfill",
                    True,
                ),
                (
                    legacy_document_id,
                    legacy_version_id,
                    legacy_provenance_id,
                    "legacy-backfill",
                    False,
                ),
            ):
                await temporary_connection.execute(
                    "INSERT INTO legal_documents (id, source_id, external_id) VALUES ($1, $2, $3)",
                    document_id,
                    "TESTM08",
                    external_id,
                )
                await temporary_connection.execute(
                    "INSERT INTO document_versions ("
                    "id, document_id, version_number, raw_html, normalized_text, snapshot_sha256, "
                    "source_content_sha256, normalized_text_sha256, normalizer_version, "
                    "normalized_block_count) VALUES ($1, $2, 1, 'text', 'text', "
                    "$3, $3, $3, 'test', 1)",
                    version_id,
                    document_id,
                    "a" * 64,
                )
                await temporary_connection.execute(
                    "INSERT INTO source_provenance_records ("
                    "id, document_version_id, provenance_type, source_id, transport, operation, "
                    "retrieved_at, tls_verified) VALUES ($1, $2, 'source_fetch', 'TESTM08', "
                    "'TEST', 'migration_backfill', now(), $3)",
                    provenance_id,
                    version_id,
                    tls_verified,
                )
        finally:
            await temporary_connection.close()

        _run_alembic(["upgrade", "head"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            await _assert_head_schema(temporary_connection)
            backfilled_trust = {
                row["tls_verified"]: (
                    row["transport_trust_mode"],
                    row["tls_chain_verified"],
                    row["tls_hostname_verified"],
                )
                for row in await temporary_connection.fetch(
                    "SELECT tls_verified, transport_trust_mode, tls_chain_verified, "
                    "tls_hostname_verified "
                    "FROM source_provenance_records WHERE source_id = 'TESTM08'"
                )
            }
            assert backfilled_trust == {
                True: ("STRICT_TLS", True, True),
                False: ("LEGACY_UNVERIFIED", False, False),
            }
        finally:
            await temporary_connection.close()

        _run_alembic(["downgrade", "0004_conversation_state"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            await _assert_revision_four_schema(temporary_connection)
        finally:
            await temporary_connection.close()

        _run_alembic(["upgrade", "head"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            await _assert_head_schema(temporary_connection)
        finally:
            await temporary_connection.close()

        _run_alembic(["downgrade", "0001_enable_pgvector"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            await _assert_revision_one_schema(temporary_connection)
        finally:
            await temporary_connection.close()

        _run_alembic(["upgrade", "head"], temporary_database_url)
        temporary_connection = await _connect(source_url, temporary_database)
        try:
            await _assert_head_schema(temporary_connection)
        finally:
            await temporary_connection.close()
    finally:
        try:
            await _drop_database(admin_connection, temporary_database)
        finally:
            await admin_connection.close()
