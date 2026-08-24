"""Disposable, synthetic-only Prompt-03 Gate-3 evaluation harness."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
from sqlalchemy import select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from legal_chatbot.documents.orm import (
    CitationRecord,
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    RetrievalRun,
    ReviewedLegalEffectAssertion,
    SourceProvenanceRecord,
)
from legal_chatbot.legal_effects import (
    ReviewedLegalEffectsImporter,
    ReviewedLegalEffectsManualPolicy,
    ReviewedLegalEffectsShadowEvaluator,
    ReviewedLegalEffectsShadowOutcome,
    ReviewedLegalEffectsShadowSettings,
    ShadowFamilyRef,
    parse_reviewed_legal_effects_artifact,
)
from legal_chatbot.sources.models import ProvenanceType, TransportTrustMode

_ROOT = Path(__file__).resolve().parents[3]
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
class Prompt03ShadowEvaluationSummary:
    """Content-free aggregate evidence from one disposable evaluation run."""

    scenario_count: int
    outcome_counts: Counter[str] = field(repr=False)
    privilege_checks_pass: bool
    retrieval_citation_unchanged: bool
    main_db_touched: bool = False
    temporary_diagnostics: bool = True

    def to_public_dict(self) -> dict[str, object]:
        return {
            "scenario_count": self.scenario_count,
            "outcome_counts": dict(sorted(self.outcome_counts.items())),
            "privilege_checks_pass": self.privilege_checks_pass,
            "retrieval_citation_unchanged": self.retrieval_citation_unchanged,
            "main_db_touched": self.main_db_touched,
            "temporary_diagnostics": self.temporary_diagnostics,
        }


@dataclass(frozen=True)
class _Factories:
    admin: async_sessionmaker[AsyncSession]
    importer: async_sessionmaker[AsyncSession]
    shadow: async_sessionmaker[AsyncSession]


def _require(value: bool) -> None:
    if not value:
        raise RuntimeError("synthetic_shadow_evaluation_failed")


def _sha(value: str) -> str:
    return value * 64


def _artifact(
    provenance_id: UUID,
    artifact_id: str,
    family_id: str,
    relation_id: str,
    relation_kind: str,
    events: list[dict[str, str]] | None = None,
):
    subject = {
        "source_id": "UEB",
        "external_id": "synthetic-shadow-subject",
        "snapshot_sha256": _sha("a"),
        "normalized_text_sha256": _sha("b"),
    }
    object_endpoint = {
        "source_id": "UEB",
        "external_id": "synthetic-shadow-object",
        "snapshot_sha256": _sha("c"),
        "normalized_text_sha256": _sha("d"),
    }
    return parse_reviewed_legal_effects_artifact(
        {
            "schema_version": "reviewed-legal-effects-v1",
            "profile_state": "APPROVED_SCHEMA_DEFAULT_OFF",
            "artifact_id": artifact_id,
            "approval": {
                "submitted_by": "synthetic-submitter",
                "submitted_at": "2026-08-24T09:00:00Z",
                "reviewer_role": "LEGAL_REVIEWER",
                "reviewed_by": "synthetic-reviewer",
                "reviewed_at": "2026-08-24T10:00:00Z",
                "approver_role": "LEGAL_APPROVER",
                "approved_by": "synthetic-approver",
                "approved_at": "2026-08-24T11:00:00Z",
            },
            "families": [
                {
                    "family_id": family_id,
                    "completeness": "DECLARED_PARTIAL",
                    "scope_note": "Synthetic shadow scope only.",
                }
            ],
            "relations": [
                {
                    "relation_id": relation_id,
                    "family_id": family_id,
                    "subject": subject,
                    "object": object_endpoint,
                    "relation_kind": relation_kind,
                    "effect_state": "EFFECT_NOT_MODELED",
                    "basis": {
                        "endpoint": subject,
                        "provenance_id": str(provenance_id),
                        "locator": {"kind": "ARTICLE", "value": "Synthetic article"},
                    },
                }
            ],
            "events": events or [],
        }
    )


async def _connect(url: URL, database: str) -> asyncpg.Connection:
    if url.host is None or url.username is None or url.password is None:
        raise RuntimeError("synthetic_shadow_evaluation_failed")
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
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("synthetic_shadow_evaluation_failed")


async def _seed(factory: async_sessionmaker[AsyncSession]) -> tuple[UUID, UUID]:
    manual_provenance, source_provenance = uuid4(), uuid4()
    subject_document, object_document = uuid4(), uuid4()
    subject_version, object_version = uuid4(), uuid4()
    async with factory.begin() as session:
        session.add_all(
            [
                LegalDocument(
                    id=subject_document,
                    source_id="UEB",
                    external_id="synthetic-shadow-subject",
                ),
                LegalDocument(
                    id=object_document,
                    source_id="UEB",
                    external_id="synthetic-shadow-object",
                ),
                DocumentVersion(
                    id=subject_version,
                    document_id=subject_document,
                    version_number=1,
                    raw_html="synthetic",
                    normalized_text="synthetic",
                    snapshot_sha256=_sha("a"),
                    source_content_sha256=_sha("a"),
                    normalized_text_sha256=_sha("b"),
                    normalizer_version="synthetic-v1",
                    normalized_block_count=1,
                ),
                DocumentVersion(
                    id=object_version,
                    document_id=object_document,
                    version_number=1,
                    raw_html="synthetic",
                    normalized_text="synthetic",
                    snapshot_sha256=_sha("c"),
                    source_content_sha256=_sha("c"),
                    normalized_text_sha256=_sha("d"),
                    normalizer_version="synthetic-v1",
                    normalized_block_count=1,
                ),
                SourceProvenanceRecord(
                    id=manual_provenance,
                    document_version_id=subject_version,
                    provenance_type=ProvenanceType.MANUAL_SNAPSHOT.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_shadow",
                    retrieved_at=_NOW,
                    tls_verified=True,
                    tls_chain_verified=True,
                    tls_hostname_verified=True,
                    transport_trust_mode=TransportTrustMode.STRICT_TLS.value,
                ),
                SourceProvenanceRecord(
                    id=source_provenance,
                    document_version_id=subject_version,
                    provenance_type=ProvenanceType.SOURCE_FETCH.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_shadow",
                    retrieved_at=_NOW,
                    tls_verified=True,
                    tls_chain_verified=True,
                    tls_hostname_verified=True,
                    transport_trust_mode=TransportTrustMode.STRICT_TLS.value,
                ),
                SourceProvenanceRecord(
                    document_version_id=object_version,
                    provenance_type=ProvenanceType.MANUAL_SNAPSHOT.value,
                    source_id="UEB",
                    transport="synthetic",
                    operation="synthetic_shadow",
                    retrieved_at=_NOW,
                    tls_verified=True,
                    tls_chain_verified=True,
                    tls_hostname_verified=True,
                    transport_trust_mode=TransportTrustMode.STRICT_TLS.value,
                ),
                DocumentChunk(
                    document_version_id=subject_version,
                    ordinal=0,
                    content_text="synthetic",
                    start_char=0,
                    end_char=9,
                    content_sha256=_sha("e"),
                    chunker_version="synthetic-v1",
                    locator={"kind": "article", "label": "Synthetic article"},
                ),
            ]
        )
    return manual_provenance, source_provenance


async def _privileges(factory: _Factories) -> bool:
    for role_factory in (factory.importer, factory.shadow):
        async with role_factory() as session:
            for table_name in (*_EVIDENCE_TABLES, *_REGISTRY_TABLES):
                allowed = await session.scalar(
                    text("SELECT has_table_privilege(current_user, :table_name, 'SELECT')"),
                    {"table_name": table_name},
                )
                if allowed is not True:
                    return False
    async with factory.importer() as session:
        for table_name in _REGISTRY_TABLES:
            allowed = await session.scalar(
                text("SELECT has_table_privilege(current_user, :table_name, 'INSERT')"),
                {"table_name": table_name},
            )
            if allowed is not True:
                return False
        try:
            await session.execute(text("DELETE FROM reviewed_legal_effect_imports"))
        except DBAPIError:
            await session.rollback()
        else:
            return False
    async with factory.shadow() as session:
        for table_name in _REGISTRY_TABLES:
            allowed = await session.scalar(
                text("SELECT has_table_privilege(current_user, :table_name, 'INSERT')"),
                {"table_name": table_name},
            )
            if allowed is not False:
                return False
        try:
            await session.execute(
                text("UPDATE reviewed_legal_effect_imports SET runtime_enabled = false")
            )
        except DBAPIError:
            await session.rollback()
        else:
            return False
    return True


async def _run(database_url: str) -> Prompt03ShadowEvaluationSummary:
    url = make_url(database_url)
    database_name = f"prompt03_shadow_{uuid4().hex}"
    role_names = (f"prompt03_importer_{uuid4().hex}", f"prompt03_shadow_{uuid4().hex}")
    password = "synthetic-only-password"
    admin = await _connect(url, "postgres")
    admin_engine = importer_engine = shadow_engine = None
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        disposable_url = url.set(database=database_name).render_as_string(hide_password=False)
        _upgrade(disposable_url)
        admin_engine = create_async_engine(disposable_url)
        async with admin_engine.begin() as connection:
            for role_name in role_names:
                await connection.execute(
                    text(f"CREATE ROLE \"{role_name}\" LOGIN PASSWORD '{password}'")
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
            url.set(database=database_name, username=role_names[0], password=password)
        )
        shadow_engine = create_async_engine(
            url.set(database=database_name, username=role_names[1], password=password)
        )
        factories = _Factories(
            admin=async_sessionmaker(admin_engine, class_=AsyncSession, expire_on_commit=False),
            importer=async_sessionmaker(
                importer_engine, class_=AsyncSession, expire_on_commit=False
            ),
            shadow=async_sessionmaker(shadow_engine, class_=AsyncSession, expire_on_commit=False),
        )
        manual_provenance, source_provenance = await _seed(factories.admin)
        privilege_checks_pass = await _privileges(factories)
        importer = ReviewedLegalEffectsImporter(factories.importer, clock=lambda: _NOW)
        enabled = ReviewedLegalEffectsShadowEvaluator(
            factories.shadow,
            ReviewedLegalEffectsShadowSettings(
                enabled=True,
                manual_policy=ReviewedLegalEffectsManualPolicy.HASH_PINNED_PILOT_ALLOWED,
            ),
        )
        disabled = ReviewedLegalEffectsShadowEvaluator(
            factories.shadow, ReviewedLegalEffectsShadowSettings()
        )
        async with factories.admin() as session:
            retrieval_before = len((await session.scalars(select(RetrievalRun))).all())
            citation_before = len((await session.scalars(select(CitationRecord))).all())

        manual = _artifact(
            manual_provenance, "shadow-manual", "family-manual", "assertion-manual", "IMPLEMENTS"
        )
        source = _artifact(
            source_provenance, "shadow-source", "family-source", "assertion-source", "GOVERNS"
        )
        manual_import = await importer.import_artifact(manual, "synthetic-operator")
        _require(manual_import.status.value == "IMPORTED")
        manual_result = await enabled.evaluate(ShadowFamilyRef("shadow-manual", "family-manual"))
        _require(
            manual_result.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_ELIGIBLE
            and manual_result.manual_snapshot_basis_count == 1
            and manual_result.manual_snapshot_caveat
        )
        source_import = await importer.import_artifact(source, "synthetic-operator")
        _require(source_import.status.value == "IMPORTED")
        source_result = await enabled.evaluate(ShadowFamilyRef("shadow-source", "family-source"))
        _require(
            source_result.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_ELIGIBLE
            and source_result.source_fetch_basis_count == 1
            and not source_result.manual_snapshot_caveat
        )
        correction = _artifact(
            manual_provenance,
            "shadow-correction",
            "family-correction",
            "assertion-correction",
            "IMPLEMENTS",
            [
                {
                    "event_id": "event-correction",
                    "assertion_id": "assertion-manual",
                    "kind": "CORRECTS",
                    "successor_relation_id": "assertion-correction",
                    "reason_code": "SUPERSEDED_BY_REVIEW",
                    "reason_note": "Synthetic correction only.",
                }
            ],
        )
        correction_import = await importer.import_artifact(correction, "synthetic-operator")
        _require(correction_import.status.value == "IMPORTED")
        suppressed = await enabled.evaluate(ShadowFamilyRef("shadow-manual", "family-manual"))
        _require(suppressed.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_SUPPRESSED_EVENT)
        unresolved = await enabled.evaluate(ShadowFamilyRef("missing-import", "family-missing"))
        _require(unresolved.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED)
        rejected = await enabled.evaluate(ShadowFamilyRef("unsafe input", "family-source"))
        _require(rejected.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_INPUT_REJECTED)
        disabled_result = await disabled.evaluate(ShadowFamilyRef("shadow-source", "family-source"))
        _require(disabled_result.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_DISABLED)
        async with factories.admin.begin() as session:
            source_assertion = await session.scalar(
                select(ReviewedLegalEffectAssertion).where(
                    ReviewedLegalEffectAssertion.assertion_id == "assertion-source"
                )
            )
            if source_assertion is None:
                raise RuntimeError("synthetic_shadow_evaluation_failed")
            session.add(
                ReviewedLegalEffectAssertion(
                    assertion_id="assertion-direct-duplicate",
                    import_id=source_assertion.import_id,
                    family_id=source_assertion.family_id,
                    subject_document_version_id=source_assertion.subject_document_version_id,
                    object_document_version_id=source_assertion.object_document_version_id,
                    relation_kind=source_assertion.relation_kind,
                    effect_state=source_assertion.effect_state,
                    basis_document_version_id=source_assertion.basis_document_version_id,
                    basis_source_provenance_record_id=(
                        source_assertion.basis_source_provenance_record_id
                    ),
                    basis_locator_type=source_assertion.basis_locator_type,
                    basis_locator_value=source_assertion.basis_locator_value,
                    reviewed_by=source_assertion.reviewed_by,
                    reviewed_at=source_assertion.reviewed_at,
                    approved_by=source_assertion.approved_by,
                    approved_at=source_assertion.approved_at,
                    created_at=_NOW,
                )
            )
        conflict = await enabled.evaluate(ShadowFamilyRef("shadow-source", "family-source"))
        _require(conflict.outcome is ReviewedLegalEffectsShadowOutcome.SHADOW_CONFLICT)
        async with factories.admin() as session:
            retrieval_unchanged = (
                len((await session.scalars(select(RetrievalRun))).all()) == retrieval_before
                and len((await session.scalars(select(CitationRecord))).all()) == citation_before
            )
        outcomes = Counter(
            result.outcome.value
            for result in (
                disabled_result,
                manual_result,
                source_result,
                suppressed,
                unresolved,
                conflict,
                rejected,
            )
        )
        return Prompt03ShadowEvaluationSummary(
            scenario_count=sum(outcomes.values()),
            outcome_counts=outcomes,
            privilege_checks_pass=privilege_checks_pass,
            retrieval_citation_unchanged=retrieval_unchanged,
        )
    finally:
        if importer_engine is not None:
            await importer_engine.dispose()
        if shadow_engine is not None:
            await shadow_engine.dispose()
        if admin_engine is not None:
            async with admin_engine.begin() as connection:
                for role_name in role_names:
                    await connection.execute(text(f'DROP OWNED BY "{role_name}"'))
                    await connection.execute(text(f'DROP ROLE IF EXISTS "{role_name}"'))
            await admin_engine.dispose()
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()


def run_prompt03_shadow_evaluation(database_url: str) -> Prompt03ShadowEvaluationSummary:
    """Synchronously run the harness; callers must supply a Settings-derived URL."""

    return asyncio.run(_run(database_url))
