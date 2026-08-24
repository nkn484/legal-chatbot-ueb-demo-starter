"""Opt-in, disposable-PostgreSQL coverage for synthetic reviewed-effect imports."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from legal_chatbot.core.config import Settings
from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    ReviewedLegalEffectAssertion,
    ReviewedLegalEffectEvent,
    ReviewedLegalEffectFamily,
    ReviewedLegalEffectImport,
    SourceProvenanceRecord,
)
from legal_chatbot.legal_effects import (
    LegalEffectsErrorCode,
    LegalEffectsImportError,
    ReviewedLegalEffectsImporter,
    ReviewedLegalEffectsManualPolicy,
    ReviewedLegalEffectsShadowEvaluator,
    ReviewedLegalEffectsShadowOutcome,
    ReviewedLegalEffectsShadowSettings,
    ShadowFamilyRef,
    parse_reviewed_legal_effects_artifact,
)
from legal_chatbot.legal_effects.canonical import canonical_artifact_sha256
from legal_chatbot.legal_effects.models import ReviewedLegalEffectsArtifact
from legal_chatbot.sources.models import ProvenanceType, TransportTrustMode

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 to use PostgreSQL"
    ),
]

_ROOT = Path(__file__).resolve().parents[2]
_NOW = datetime(2026, 8, 24, 12, tzinfo=UTC)
_EVIDENCE_TABLES = (
    "legal_documents",
    "document_versions",
    "source_provenance_records",
    "document_chunks",
)
_REGISTRY_TABLES = (
    "reviewed_legal_effect_imports",
    "reviewed_legal_effect_families",
    "reviewed_legal_effect_assertions",
    "reviewed_legal_effect_events",
)


@dataclass(frozen=True)
class _SessionFactories:
    admin: async_sessionmaker[AsyncSession]
    importer: async_sessionmaker[AsyncSession]
    shadow: async_sessionmaker[AsyncSession]

    def __call__(self) -> AsyncSession:
        return self.admin()

    def begin(self):
        return self.admin.begin()


async def _connect(url: URL, database: str) -> asyncpg.Connection:
    if url.host is None or url.username is None or url.password is None:
        raise RuntimeError("DATABASE_URL must include host, user, and password")
    return await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=database,
    )


def _upgrade(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, "Alembic setup command failed"


@pytest.fixture
async def session_factory() -> AsyncIterator[_SessionFactories]:
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        try:
            database_url = Settings().database_url.get_secret_value()  # type: ignore[call-arg]
        except Exception:
            pytest.skip("DATABASE_URL is required for disposable PostgreSQL integration coverage")
    url = make_url(database_url)
    database_name = f"reviewed_effects_{uuid4().hex}"
    admin = await _connect(url, "postgres")
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    disposable_url = url.set(database=database_name).render_as_string(hide_password=False)
    engine = importer_engine = shadow_engine = None
    role_names = (f"prompt03_importer_{uuid4().hex}", f"prompt03_shadow_{uuid4().hex}")
    role_password = "synthetic-only-password"
    try:
        _upgrade(disposable_url)
        engine = create_async_engine(disposable_url)
        async with engine.begin() as connection:
            for role_name in role_names:
                await connection.execute(
                    text(f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{role_password}'"),
                )
                await connection.execute(
                    text(f'GRANT CONNECT ON DATABASE "{database_name}" TO "{role_name}"')
                )
                await connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role_name}"'))
                await connection.execute(
                    text(f'GRANT SELECT ON TABLE {", ".join(_EVIDENCE_TABLES)} TO "{role_name}"')
                )
                await connection.execute(
                    text(f'GRANT SELECT ON TABLE {", ".join(_REGISTRY_TABLES)} TO "{role_name}"')
                )
            await connection.execute(
                text(f'GRANT INSERT ON TABLE {", ".join(_REGISTRY_TABLES)} TO "{role_names[0]}"')
            )
        importer_engine = create_async_engine(
            url.set(database=database_name, username=role_names[0], password=role_password)
        )
        shadow_engine = create_async_engine(
            url.set(database=database_name, username=role_names[1], password=role_password)
        )
        yield _SessionFactories(
            admin=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
            importer=async_sessionmaker(
                importer_engine, class_=AsyncSession, expire_on_commit=False
            ),
            shadow=async_sessionmaker(shadow_engine, class_=AsyncSession, expire_on_commit=False),
        )
    finally:
        if importer_engine is not None:
            await importer_engine.dispose()
        if shadow_engine is not None:
            await shadow_engine.dispose()
        if engine is not None:
            async with engine.begin() as connection:
                for role_name in role_names:
                    await connection.execute(text(f'DROP OWNED BY "{role_name}"'))
                    await connection.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))
            await engine.dispose()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()


def _sha(character: str) -> str:
    return character * 64


def _artifact(
    provenance_id: UUID,
    *,
    artifact_id: str = "synthetic-import",
    subject_external_id: str = "synthetic-subject",
    subject_hash: str = "a",
    object_external_id: str = "synthetic-object",
    object_hash: str = "c",
    locator: str = "Article one",
) -> ReviewedLegalEffectsArtifact:
    subject = {
        "source_id": "UEB",
        "external_id": subject_external_id,
        "snapshot_sha256": _sha(subject_hash),
        "normalized_text_sha256": _sha(chr(ord(subject_hash) + 1)),
    }
    object_endpoint = {
        "source_id": "UEB",
        "external_id": object_external_id,
        "snapshot_sha256": _sha(object_hash),
        "normalized_text_sha256": _sha(chr(ord(object_hash) + 1)),
    }
    return parse_reviewed_legal_effects_artifact(
        {
            "schema_version": "reviewed-legal-effects-v1",
            "profile_state": "APPROVED_SCHEMA_DEFAULT_OFF",
            "artifact_id": artifact_id,
            "approval": {
                "submitted_by": "submitter",
                "submitted_at": "2026-08-24T09:00:00Z",
                "reviewer_role": "LEGAL_REVIEWER",
                "reviewed_by": "reviewer",
                "reviewed_at": "2026-08-24T10:00:00Z",
                "approver_role": "LEGAL_APPROVER",
                "approved_by": "approver",
                "approved_at": "2026-08-24T11:00:00Z",
            },
            "families": [
                {
                    "family_id": "synthetic-family",
                    "completeness": "DECLARED_COMPLETE",
                    "scope_note": "Synthetic declared scope only.",
                }
            ],
            "relations": [
                {
                    "relation_id": f"relation-{artifact_id}",
                    "family_id": "synthetic-family",
                    "subject": subject,
                    "object": object_endpoint,
                    "relation_kind": "IMPLEMENTS",
                    "effect_state": "EFFECT_NOT_MODELED",
                    "basis": {
                        "endpoint": subject,
                        "provenance_id": str(provenance_id),
                        "locator": {"kind": "ARTICLE", "value": locator},
                    },
                }
            ],
        }
    )


def _with_events(
    artifact: ReviewedLegalEffectsArtifact, events: list[dict[str, str]]
) -> ReviewedLegalEffectsArtifact:
    payload = artifact.model_dump(mode="json")
    payload["events"] = events
    return parse_reviewed_legal_effects_artifact(payload)


def _reversed_artifact(
    provenance_id: UUID, artifact_id: str, events: list[dict[str, str]]
) -> ReviewedLegalEffectsArtifact:
    payload = _artifact(provenance_id, artifact_id=artifact_id).model_dump(mode="json")
    relation = payload["relations"][0]
    relation["subject"], relation["object"] = relation["object"], relation["subject"]
    payload["events"] = events
    return parse_reviewed_legal_effects_artifact(payload)


def _governs_artifact(
    provenance_id: UUID, artifact_id: str, events: list[dict[str, str]]
) -> ReviewedLegalEffectsArtifact:
    payload = _artifact(provenance_id, artifact_id=artifact_id).model_dump(mode="json")
    payload["relations"][0]["relation_kind"] = "GOVERNS"
    payload["events"] = events
    return parse_reviewed_legal_effects_artifact(payload)


async def _seed(session_factory: _SessionFactories) -> tuple[UUID, UUID, UUID, UUID]:
    (
        subject_provenance_id,
        untrusted_provenance_id,
        object_provenance_id,
        source_fetch_provenance_id,
    ) = (uuid4(), uuid4(), uuid4(), uuid4())
    subject_document_id, object_document_id = uuid4(), uuid4()
    subject_version_id, object_version_id = uuid4(), uuid4()
    async with session_factory.begin() as session:
        session.add_all(
            [
                LegalDocument(
                    id=subject_document_id, source_id="UEB", external_id="synthetic-subject"
                ),
                LegalDocument(
                    id=object_document_id, source_id="UEB", external_id="synthetic-object"
                ),
                DocumentVersion(
                    id=subject_version_id,
                    document_id=subject_document_id,
                    version_number=1,
                    raw_html="synthetic subject",
                    normalized_text="synthetic subject",
                    snapshot_sha256=_sha("a"),
                    source_content_sha256=_sha("a"),
                    normalized_text_sha256=_sha("b"),
                    normalizer_version="synthetic-v1",
                    normalized_block_count=1,
                ),
                DocumentVersion(
                    id=object_version_id,
                    document_id=object_document_id,
                    version_number=1,
                    raw_html="synthetic object",
                    normalized_text="synthetic object",
                    snapshot_sha256=_sha("c"),
                    source_content_sha256=_sha("c"),
                    normalized_text_sha256=_sha("d"),
                    normalizer_version="synthetic-v1",
                    normalized_block_count=1,
                ),
                SourceProvenanceRecord(
                    id=subject_provenance_id,
                    document_version_id=subject_version_id,
                    provenance_type=ProvenanceType.MANUAL_SNAPSHOT.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_import_test",
                    retrieved_at=_NOW,
                    tls_verified=True,
                    tls_chain_verified=True,
                    tls_hostname_verified=True,
                    transport_trust_mode=TransportTrustMode.STRICT_TLS.value,
                ),
                SourceProvenanceRecord(
                    id=untrusted_provenance_id,
                    document_version_id=subject_version_id,
                    provenance_type=ProvenanceType.MANUAL_SNAPSHOT.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_import_test",
                    retrieved_at=_NOW,
                    tls_verified=False,
                    tls_chain_verified=False,
                    tls_hostname_verified=False,
                    transport_trust_mode=TransportTrustMode.LEGACY_UNVERIFIED.value,
                ),
                SourceProvenanceRecord(
                    id=source_fetch_provenance_id,
                    document_version_id=subject_version_id,
                    provenance_type=ProvenanceType.SOURCE_FETCH.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_import_test",
                    retrieved_at=_NOW,
                    tls_verified=True,
                    tls_chain_verified=True,
                    tls_hostname_verified=True,
                    transport_trust_mode=TransportTrustMode.STRICT_TLS.value,
                ),
                SourceProvenanceRecord(
                    id=object_provenance_id,
                    document_version_id=object_version_id,
                    provenance_type=ProvenanceType.MANUAL_SNAPSHOT.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_import_test",
                    retrieved_at=_NOW,
                    tls_verified=True,
                    tls_chain_verified=True,
                    tls_hostname_verified=True,
                    transport_trust_mode=TransportTrustMode.STRICT_TLS.value,
                ),
                DocumentChunk(
                    document_version_id=subject_version_id,
                    ordinal=0,
                    content_text="synthetic chunk",
                    start_char=0,
                    end_char=15,
                    content_sha256=_sha("e"),
                    chunker_version="synthetic-v1",
                    locator={"kind": "article", "label": "  ARTICLE ONE "},
                ),
            ]
        )
    return (
        subject_provenance_id,
        untrusted_provenance_id,
        object_provenance_id,
        source_fetch_provenance_id,
    )


@pytest.mark.asyncio
async def test_reviewed_legal_effects_importer_uses_disposable_database_and_manual_strict_basis(
    session_factory: _SessionFactories,
) -> None:
    (
        provenance_id,
        untrusted_provenance_id,
        object_provenance_id,
        source_fetch_provenance_id,
    ) = await _seed(session_factory)
    importer = ReviewedLegalEffectsImporter(session_factory.importer, clock=lambda: _NOW)
    artifact = _artifact(provenance_id)

    for role_factory in (session_factory.importer, session_factory.shadow):
        async with role_factory() as session:
            for table_name in (*_EVIDENCE_TABLES, *_REGISTRY_TABLES):
                assert await session.scalar(
                    text("SELECT has_table_privilege(current_user, :table_name, 'SELECT')"),
                    {"table_name": table_name},
                ) is True
    async with session_factory.importer() as session:
        for table_name in _REGISTRY_TABLES:
            assert await session.scalar(
                text("SELECT has_table_privilege(current_user, :table_name, 'INSERT')"),
                {"table_name": table_name},
            ) is True
            assert await session.scalar(
                text("SELECT has_table_privilege(current_user, :table_name, 'UPDATE')"),
                {"table_name": table_name},
            ) is False
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM reviewed_legal_effect_imports"))
        await session.rollback()
    async with session_factory.shadow() as session:
        for table_name in _REGISTRY_TABLES:
            assert await session.scalar(
                text("SELECT has_table_privilege(current_user, :table_name, 'INSERT')"),
                {"table_name": table_name},
            ) is False
            assert await session.scalar(
                text("SELECT has_table_privilege(current_user, :table_name, 'DELETE')"),
                {"table_name": table_name},
            ) is False
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE reviewed_legal_effect_imports SET runtime_enabled = false")
            )
        await session.rollback()
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM reviewed_legal_effect_imports"))
        await session.rollback()

    result = await importer.import_artifact(artifact, "synthetic-operator")
    assert result.status.value == "IMPORTED"
    assert result.import_count == result.family_count == result.assertion_count == 1
    assert result.event_count == 0
    assert result.manual_basis_count == 1
    assert result.source_fetch_basis_count == 0
    assert len(result.artifact_hash_prefix) == 12
    assert "synthetic-import" not in repr(result)

    repeated = await importer.import_artifact(artifact, "synthetic-operator")
    assert repeated.status.value == "ALREADY_IMPORTED"
    assert (
        repeated.import_count,
        repeated.family_count,
        repeated.assertion_count,
        repeated.event_count,
        repeated.manual_basis_count,
        repeated.source_fetch_basis_count,
    ) == (0, 0, 0, 0, 0, 0)

    shadow = ReviewedLegalEffectsShadowEvaluator(
        session_factory.shadow,
        ReviewedLegalEffectsShadowSettings(
            enabled=True,
            manual_policy=ReviewedLegalEffectsManualPolicy.HASH_PINNED_PILOT_ALLOWED,
        ),
    )
    manual_eligible = await shadow.evaluate(ShadowFamilyRef("synthetic-import", "synthetic-family"))
    assert manual_eligible.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_ELIGIBLE
    assert manual_eligible.manual_snapshot_basis_count == 1
    assert manual_eligible.manual_snapshot_caveat is True

    correction = _with_events(
        _artifact(provenance_id, artifact_id="synthetic-correction"),
        [
            {
                "event_id": "synthetic-corrects",
                "assertion_id": "relation-synthetic-import",
                "kind": "CORRECTS",
                "successor_relation_id": "relation-synthetic-correction",
                "reason_code": "SUPERSEDED_BY_REVIEW",
                "reason_note": "Synthetic correction only.",
            }
        ],
    )
    correction_result = await importer.import_artifact(correction, "synthetic-operator")
    assert correction_result.status.value == "IMPORTED"
    async with session_factory() as session:
        active_ids = set(
            (
                await session.scalars(
                    select(ReviewedLegalEffectAssertion.assertion_id).where(
                        ~select(ReviewedLegalEffectEvent.event_id)
                        .where(
                            ReviewedLegalEffectEvent.assertion_id
                            == ReviewedLegalEffectAssertion.assertion_id
                        )
                        .exists()
                    )
                )
            ).all()
        )
    assert "relation-synthetic-import" not in active_ids
    assert "relation-synthetic-correction" in active_ids

    revocation = _reversed_artifact(
        provenance_id,
        "synthetic-revocation",
        [
            {
                "event_id": "synthetic-revokes",
                "assertion_id": "relation-synthetic-correction",
                "kind": "REVOKES",
                "reason_code": "WITHDRAWN_BY_REVIEW",
                "reason_note": "Synthetic revocation only.",
            }
        ],
    )
    revocation_result = await importer.import_artifact(revocation, "synthetic-operator")
    assert revocation_result.status.value == "IMPORTED"

    async with session_factory() as session:
        stored_import = await session.scalar(select(ReviewedLegalEffectImport))
        assertion = await session.scalar(select(ReviewedLegalEffectAssertion))
        assert stored_import is not None and stored_import.runtime_enabled is False
        assert assertion is not None
        assert assertion.basis_source_provenance_record_id == provenance_id
        assert len((await session.scalars(select(ReviewedLegalEffectFamily))).all()) == 3
        events = (await session.scalars(select(ReviewedLegalEffectEvent))).all()
        assert {(event.event_kind, event.assertion_id) for event in events} == {
            ("CORRECTS", "relation-synthetic-import"),
            ("REVOKES", "relation-synthetic-correction"),
        }
        active_ids = set(
            (
                await session.scalars(
                    select(ReviewedLegalEffectAssertion.assertion_id).where(
                        ~select(ReviewedLegalEffectEvent.event_id)
                        .where(
                            ReviewedLegalEffectEvent.assertion_id
                            == ReviewedLegalEffectAssertion.assertion_id
                        )
                        .exists()
                    )
                )
            ).all()
        )
        assert "relation-synthetic-correction" not in active_ids
        assert "relation-synthetic-revocation" in active_ids
        with pytest.raises(DBAPIError):
            await session.execute(
                text("UPDATE reviewed_legal_effect_imports SET imported_by = 'changed'")
            )
        await session.rollback()
        with pytest.raises(DBAPIError):
            await session.execute(text("DELETE FROM reviewed_legal_effect_assertions"))
        await session.rollback()

    with pytest.raises(LegalEffectsImportError) as locator_error:
        await importer.import_artifact(
            _artifact(provenance_id, artifact_id="bad-locator", locator="missing locator"),
            "synthetic-operator",
        )
    assert locator_error.value.code is LegalEffectsErrorCode.LOCATOR_INVALID

    with pytest.raises(LegalEffectsImportError) as endpoint_error:
        await importer.import_artifact(
            _artifact(provenance_id, artifact_id="missing-endpoint", subject_external_id="missing"),
            "synthetic-operator",
        )
    assert endpoint_error.value.code is LegalEffectsErrorCode.ENDPOINT_NOT_FOUND

    with pytest.raises(LegalEffectsImportError) as version_error:
        await importer.import_artifact(
            _artifact(provenance_id, artifact_id="wrong-version", subject_hash="e"),
            "synthetic-operator",
        )
    assert version_error.value.code is LegalEffectsErrorCode.VERSION_HASH_MISMATCH

    with pytest.raises(LegalEffectsImportError) as missing_provenance_error:
        await importer.import_artifact(
            _artifact(uuid4(), artifact_id="missing-provenance"), "synthetic-operator"
        )
    assert missing_provenance_error.value.code is LegalEffectsErrorCode.PROVENANCE_NOT_FOUND

    with pytest.raises(LegalEffectsImportError) as wrong_provenance_error:
        await importer.import_artifact(
            _artifact(object_provenance_id, artifact_id="wrong-provenance"), "synthetic-operator"
        )
    assert wrong_provenance_error.value.code is LegalEffectsErrorCode.PROVENANCE_VERSION_MISMATCH

    with pytest.raises(LegalEffectsImportError) as trust_error:
        await importer.import_artifact(
            _artifact(untrusted_provenance_id, artifact_id="untrusted-provenance"),
            "synthetic-operator",
        )
    assert trust_error.value.code is LegalEffectsErrorCode.PROVENANCE_TRUST_INELIGIBLE

    with pytest.raises(LegalEffectsImportError) as duplicate_error:
        await importer.import_artifact(
            _reversed_artifact(provenance_id, "duplicate-active", []), "synthetic-operator"
        )
    assert duplicate_error.value.code is LegalEffectsErrorCode.DUPLICATE_ASSERTION

    with pytest.raises(LegalEffectsImportError) as unknown_event_error:
        await importer.import_artifact(
            _governs_artifact(
                provenance_id,
                "unknown-event-target",
                [
                    {
                        "event_id": "unknown-target-event",
                        "assertion_id": "not-in-database",
                        "kind": "REVOKES",
                        "reason_code": "WITHDRAWN_BY_REVIEW",
                        "reason_note": "Synthetic event only.",
                    }
                ],
            ),
            "synthetic-operator",
        )
    assert unknown_event_error.value.code is LegalEffectsErrorCode.EVENT_TARGET_NOT_FOUND

    with pytest.raises(LegalEffectsImportError) as event_conflict_error:
        await importer.import_artifact(
            _governs_artifact(
                provenance_id,
                "event-target-conflict",
                [
                    {
                        "event_id": "conflicting-target-event",
                        "assertion_id": "relation-synthetic-import",
                        "kind": "REVOKES",
                        "reason_code": "WITHDRAWN_BY_REVIEW",
                        "reason_note": "Synthetic event only.",
                    }
                ],
            ),
            "synthetic-operator",
        )
    assert event_conflict_error.value.code is LegalEffectsErrorCode.EVENT_CONFLICT

    with pytest.raises(LegalEffectsImportError) as event_id_error:
        await importer.import_artifact(
            _governs_artifact(
                provenance_id,
                "event-id-conflict",
                [
                    {
                        "event_id": "synthetic-corrects",
                        "assertion_id": "relation-synthetic-import",
                        "kind": "REVOKES",
                        "reason_code": "WITHDRAWN_BY_REVIEW",
                        "reason_note": "Synthetic event only.",
                    }
                ],
            ),
            "synthetic-operator",
        )
    assert event_id_error.value.code is LegalEffectsErrorCode.EVENT_ID_CONFLICT

    future_payload = _artifact(provenance_id, artifact_id="future-approval").model_dump(mode="json")
    future_payload["approval"]["approved_at"] = "2026-08-24T13:00:00Z"
    with pytest.raises(LegalEffectsImportError) as future_error:
        await importer.import_artifact(
            parse_reviewed_legal_effects_artifact(future_payload), "synthetic-operator"
        )
    assert future_error.value.code is LegalEffectsErrorCode.APPROVAL_TIMESTAMP_FUTURE

    conflict_payload = artifact.model_dump(mode="json")
    conflict_payload["families"][0]["scope_note"] = "Different synthetic scope."
    with pytest.raises(LegalEffectsImportError) as import_id_error:
        await importer.import_artifact(
            parse_reviewed_legal_effects_artifact(conflict_payload), "synthetic-operator"
        )
    assert import_id_error.value.code is LegalEffectsErrorCode.IMPORT_ID_CONFLICT

    source_fetch_result = await importer.import_artifact(
        _governs_artifact(source_fetch_provenance_id, "source-fetch-basis", []),
        "synthetic-operator",
    )
    assert source_fetch_result.manual_basis_count == 0
    assert source_fetch_result.source_fetch_basis_count == 1

    async with session_factory() as session:
        retrieval_before = len((await session.scalars(select(RetrievalRun))).all())
        citation_before = len((await session.scalars(select(CitationRecord))).all())
    suppressed = await shadow.evaluate(ShadowFamilyRef("synthetic-import", "synthetic-family"))
    eligible = await shadow.evaluate(ShadowFamilyRef("source-fetch-basis", "synthetic-family"))
    missing = await shadow.evaluate(ShadowFamilyRef("missing-import", "synthetic-family"))
    invalid = await shadow.evaluate(ShadowFamilyRef("invalid input", "synthetic-family"))
    assert suppressed.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_SUPPRESSED_EVENT
    assert eligible.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_ELIGIBLE
    assert eligible.source_fetch_basis_count == 1
    assert eligible.manual_snapshot_caveat is False
    assert missing.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED
    assert invalid.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_INPUT_REJECTED

    async with session_factory.begin() as session:
        source_fetch_assertion = await session.scalar(
            select(ReviewedLegalEffectAssertion).where(
                ReviewedLegalEffectAssertion.assertion_id == "relation-source-fetch-basis"
            )
        )
        assert source_fetch_assertion is not None
        session.add(
            ReviewedLegalEffectAssertion(
                assertion_id="direct-duplicate-active",
                import_id=source_fetch_assertion.import_id,
                family_id=source_fetch_assertion.family_id,
                subject_document_version_id=source_fetch_assertion.subject_document_version_id,
                object_document_version_id=source_fetch_assertion.object_document_version_id,
                relation_kind=source_fetch_assertion.relation_kind,
                effect_state=source_fetch_assertion.effect_state,
                basis_document_version_id=source_fetch_assertion.basis_document_version_id,
                basis_source_provenance_record_id=(
                    source_fetch_assertion.basis_source_provenance_record_id
                ),
                basis_locator_type=source_fetch_assertion.basis_locator_type,
                basis_locator_value=source_fetch_assertion.basis_locator_value,
                reviewed_by=source_fetch_assertion.reviewed_by,
                reviewed_at=source_fetch_assertion.reviewed_at,
                approved_by=source_fetch_assertion.approved_by,
                approved_at=source_fetch_assertion.approved_at,
                created_at=_NOW,
            )
        )
    conflict = await shadow.evaluate(ShadowFamilyRef("source-fetch-basis", "synthetic-family"))
    assert conflict.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_CONFLICT
    async with session_factory() as session:
        assert len((await session.scalars(select(RetrievalRun))).all()) == retrieval_before
        assert len((await session.scalars(select(CitationRecord))).all()) == citation_before

    async with session_factory() as session:
        assert len((await session.scalars(select(ReviewedLegalEffectImport))).all()) == 4

    hash_candidate = _artifact(provenance_id, artifact_id="hash-conflict-input")
    async with session_factory.begin() as session:
        session.add(
            ReviewedLegalEffectImport(
                import_id="synthetic-hash-sentinel",
                artifact_sha256=canonical_artifact_sha256(hash_candidate),
                schema_version=hash_candidate.schema_version,
                submitted_by="submitter",
                submitted_at=datetime(2026, 8, 24, 9, tzinfo=UTC),
                reviewed_by="reviewer",
                reviewed_at=datetime(2026, 8, 24, 10, tzinfo=UTC),
                reviewer_role="LEGAL_REVIEWER",
                approved_by="approver",
                approved_at=datetime(2026, 8, 24, 11, tzinfo=UTC),
                approver_role="LEGAL_APPROVER",
                imported_at=_NOW,
                imported_by="synthetic-operator",
                runtime_enabled=False,
            )
        )
    with pytest.raises(LegalEffectsImportError) as hash_conflict_error:
        await importer.import_artifact(hash_candidate, "synthetic-operator")
    assert hash_conflict_error.value.code is LegalEffectsErrorCode.ARTIFACT_HASH_CONFLICT
