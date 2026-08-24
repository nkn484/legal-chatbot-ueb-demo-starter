"""Transactional, default-off persistence for approved reviewed-effect artifacts."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import exists, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import (
    DocumentChunk,
    DocumentVersion,
    LegalDocument,
    ReviewedLegalEffectAssertion,
    ReviewedLegalEffectEvent,
    ReviewedLegalEffectFamily,
    ReviewedLegalEffectImport,
    SourceProvenanceRecord,
)
from legal_chatbot.legal_effects.canonical import canonical_artifact_sha256
from legal_chatbot.legal_effects.errors import LegalEffectsErrorCode, LegalEffectsImportError
from legal_chatbot.legal_effects.models import Endpoint, ReviewedLegalEffectsArtifact
from legal_chatbot.legal_effects.validation import locator_matches

_OPAQUE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
_HASH_PREFIX_LENGTH = 12

# Compatibility alias for existing importer-focused tests; new consumers use validation.py.
_locator_matches = locator_matches


class ReviewedLegalEffectsImportStatus(StrEnum):
    """Bounded outcomes exposed by the importer."""

    IMPORTED = "IMPORTED"
    ALREADY_IMPORTED = "ALREADY_IMPORTED"


@dataclass(frozen=True)
class ReviewedLegalEffectsImportResult:
    """Content-free summary of one import attempt."""

    status: ReviewedLegalEffectsImportStatus
    import_count: int
    family_count: int
    assertion_count: int
    event_count: int
    manual_basis_count: int
    source_fetch_basis_count: int
    artifact_hash_prefix: str = field(repr=False)


@dataclass(frozen=True)
class _ResolvedEndpoint:
    version_id: UUID


class ReviewedLegalEffectsImporter:
    """Resolve immutable evidence and atomically persist a shadow-only artifact."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def import_artifact(
        self, artifact: ReviewedLegalEffectsArtifact, imported_by: str
    ) -> ReviewedLegalEffectsImportResult:
        """Import an approved artifact as one transaction, or safely reject it."""

        if _OPAQUE_ID.fullmatch(imported_by) is None:
            raise LegalEffectsImportError(LegalEffectsErrorCode.INVALID_IMPORTED_BY)
        imported_at = self._clock()
        if imported_at.tzinfo is None or imported_at.utcoffset() is None:
            raise LegalEffectsImportError(LegalEffectsErrorCode.PERSISTENCE_FAILURE)
        if imported_at < artifact.approval.approved_at:
            raise LegalEffectsImportError(LegalEffectsErrorCode.APPROVAL_TIMESTAMP_FUTURE)

        artifact_hash = canonical_artifact_sha256(artifact)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    return await self._import_in_transaction(
                        session, artifact, imported_by, imported_at, artifact_hash
                    )
        except LegalEffectsImportError:
            raise
        except SQLAlchemyError:
            raise LegalEffectsImportError(LegalEffectsErrorCode.PERSISTENCE_FAILURE) from None

    async def _import_in_transaction(
        self,
        session: AsyncSession,
        artifact: ReviewedLegalEffectsArtifact,
        imported_by: str,
        imported_at: datetime,
        artifact_hash: str,
    ) -> ReviewedLegalEffectsImportResult:
        existing_id = await session.scalar(
            select(ReviewedLegalEffectImport).where(
                ReviewedLegalEffectImport.import_id == artifact.artifact_id
            )
        )
        if existing_id is not None:
            if existing_id.artifact_sha256 == artifact_hash:
                return self._result(
                    ReviewedLegalEffectsImportStatus.ALREADY_IMPORTED, artifact_hash
                )
            raise LegalEffectsImportError(LegalEffectsErrorCode.IMPORT_ID_CONFLICT)
        existing_hash = await session.scalar(
            select(ReviewedLegalEffectImport).where(
                ReviewedLegalEffectImport.artifact_sha256 == artifact_hash
            )
        )
        if existing_hash is not None:
            raise LegalEffectsImportError(LegalEffectsErrorCode.ARTIFACT_HASH_CONFLICT)

        endpoints: dict[Endpoint, _ResolvedEndpoint] = {}
        for relation in artifact.relations:
            for endpoint in (relation.subject, relation.object, relation.basis.endpoint):
                if endpoint not in endpoints:
                    endpoints[endpoint] = await self._resolve_endpoint(session, endpoint)

        basis_provenance_types: dict[UUID, str] = {}
        for relation in artifact.relations:
            basis_version_id = endpoints[relation.basis.endpoint].version_id
            provenance_type = await self._resolve_basis_provenance(
                session, relation.basis.provenance_id, basis_version_id
            )
            basis_provenance_types[relation.basis.provenance_id] = provenance_type
            await self._resolve_locator(
                session,
                basis_version_id,
                relation.basis.locator.kind.value,
                relation.basis.locator.value,
            )

        correction_targets = {
            event.successor_relation_id: event.assertion_id
            for event in artifact.events
            if event.kind.value == "CORRECTS" and event.successor_relation_id is not None
        }
        relation_keys: set[tuple[UUID, UUID, str, str]] = set()
        for relation in artifact.relations:
            key = (
                endpoints[relation.subject].version_id,
                endpoints[relation.object].version_id,
                relation.relation_kind.value,
                relation.effect_state,
            )
            active_assertion_ids = await self._active_assertion_ids(session, key)
            allowed_target_id = correction_targets.get(relation.relation_id)
            if key in relation_keys or (
                active_assertion_ids and active_assertion_ids != [allowed_target_id]
            ):
                raise LegalEffectsImportError(LegalEffectsErrorCode.DUPLICATE_ASSERTION)
            relation_keys.add(key)

        approval = artifact.approval
        session.add(
            ReviewedLegalEffectImport(
                import_id=artifact.artifact_id,
                artifact_sha256=artifact_hash,
                schema_version=artifact.schema_version,
                submitted_by=approval.submitted_by,
                submitted_at=approval.submitted_at,
                reviewed_by=approval.reviewed_by,
                reviewed_at=approval.reviewed_at,
                reviewer_role=approval.reviewer_role,
                approved_by=approval.approved_by,
                approved_at=approval.approved_at,
                approver_role=approval.approver_role,
                imported_at=imported_at,
                imported_by=imported_by,
                runtime_enabled=False,
            )
        )
        # ORM rows have no persistence relationships. Stage parent tables explicitly so
        # PostgreSQL always sees each foreign-key target before its dependent rows.
        await session.flush()
        session.add_all(
            ReviewedLegalEffectFamily(
                import_id=artifact.artifact_id,
                family_id=family.family_id,
                completeness=family.completeness.value,
                scope_note=family.scope_note,
            )
            for family in artifact.families
        )
        await session.flush()
        relation_assertions: dict[str, str] = {}
        for relation in artifact.relations:
            assertion_id = relation.relation_id
            relation_assertions[relation.relation_id] = assertion_id
            session.add(
                ReviewedLegalEffectAssertion(
                    assertion_id=assertion_id,
                    import_id=artifact.artifact_id,
                    family_id=relation.family_id,
                    subject_document_version_id=endpoints[relation.subject].version_id,
                    object_document_version_id=endpoints[relation.object].version_id,
                    relation_kind=relation.relation_kind.value,
                    effect_state=relation.effect_state,
                    basis_document_version_id=endpoints[relation.basis.endpoint].version_id,
                    basis_source_provenance_record_id=relation.basis.provenance_id,
                    basis_locator_type=relation.basis.locator.kind.value,
                    basis_locator_value=relation.basis.locator.value,
                    reviewed_by=approval.reviewed_by,
                    reviewed_at=approval.reviewed_at,
                    approved_by=approval.approved_by,
                    approved_at=approval.approved_at,
                    created_at=imported_at,
                )
            )
        await session.flush()

        event_ids: set[str] = set()
        event_targets: set[str] = set()
        for event in artifact.events:
            target_id = relation_assertions.get(event.assertion_id, event.assertion_id)
            if event.event_id in event_ids:
                raise LegalEffectsImportError(LegalEffectsErrorCode.EVENT_ID_CONFLICT)
            if target_id in event_targets:
                raise LegalEffectsImportError(LegalEffectsErrorCode.EVENT_CONFLICT)
            event_ids.add(event.event_id)
            event_targets.add(target_id)
            await self._validate_event(
                session, event.event_id, event.assertion_id, relation_assertions
            )
            successor_id = (
                relation_assertions.get(event.successor_relation_id)
                if event.successor_relation_id is not None
                else None
            )
            if event.kind.value == "CORRECTS" and successor_id is None:
                raise LegalEffectsImportError(LegalEffectsErrorCode.EVENT_TARGET_NOT_FOUND)
            session.add(
                ReviewedLegalEffectEvent(
                    event_id=event.event_id,
                    assertion_id=target_id,
                    event_kind=event.kind.value,
                    successor_assertion_id=successor_id,
                    reason_code=event.reason_code.value,
                    reason_note=event.reason_note,
                    reviewed_by=approval.reviewed_by,
                    reviewed_at=approval.reviewed_at,
                    approved_by=approval.approved_by,
                    approved_at=approval.approved_at,
                    created_at=imported_at,
                )
            )
        await session.flush()
        return self._result(
            ReviewedLegalEffectsImportStatus.IMPORTED,
            artifact_hash,
            family_count=len(artifact.families),
            assertion_count=len(artifact.relations),
            event_count=len(artifact.events),
            manual_basis_count=sum(
                provenance_type == "manual_snapshot"
                for provenance_type in basis_provenance_types.values()
            ),
            source_fetch_basis_count=sum(
                provenance_type == "source_fetch"
                for provenance_type in basis_provenance_types.values()
            ),
        )

    @staticmethod
    def _result(
        status: ReviewedLegalEffectsImportStatus,
        artifact_hash: str,
        *,
        family_count: int = 0,
        assertion_count: int = 0,
        event_count: int = 0,
        manual_basis_count: int = 0,
        source_fetch_basis_count: int = 0,
    ) -> ReviewedLegalEffectsImportResult:
        return ReviewedLegalEffectsImportResult(
            status=status,
            import_count=1 if status is ReviewedLegalEffectsImportStatus.IMPORTED else 0,
            family_count=family_count,
            assertion_count=assertion_count,
            event_count=event_count,
            manual_basis_count=manual_basis_count,
            source_fetch_basis_count=source_fetch_basis_count,
            artifact_hash_prefix=artifact_hash[:_HASH_PREFIX_LENGTH],
        )

    async def _resolve_endpoint(
        self, session: AsyncSession, endpoint: Endpoint
    ) -> _ResolvedEndpoint:
        documents = list(
            (
                await session.scalars(
                    select(LegalDocument).where(
                        LegalDocument.source_id == endpoint.source_id.value,
                        LegalDocument.external_id == endpoint.external_id,
                    )
                )
            ).all()
        )
        if not documents:
            raise LegalEffectsImportError(LegalEffectsErrorCode.ENDPOINT_NOT_FOUND)
        if len(documents) != 1:
            raise LegalEffectsImportError(LegalEffectsErrorCode.ENDPOINT_AMBIGUOUS)
        versions = list(
            (
                await session.scalars(
                    select(DocumentVersion).where(
                        DocumentVersion.document_id == documents[0].id,
                        DocumentVersion.snapshot_sha256 == endpoint.snapshot_sha256,
                        DocumentVersion.normalized_text_sha256 == endpoint.normalized_text_sha256,
                    )
                )
            ).all()
        )
        if not versions:
            raise LegalEffectsImportError(LegalEffectsErrorCode.VERSION_HASH_MISMATCH)
        if len(versions) != 1:
            raise LegalEffectsImportError(LegalEffectsErrorCode.ENDPOINT_AMBIGUOUS)
        if not await session.scalar(
            select(
                exists().where(
                    SourceProvenanceRecord.document_version_id == versions[0].id,
                    SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                )
            )
        ):
            raise LegalEffectsImportError(LegalEffectsErrorCode.PROVENANCE_TRUST_INELIGIBLE)
        return _ResolvedEndpoint(version_id=versions[0].id)

    async def _resolve_basis_provenance(
        self, session: AsyncSession, provenance_id: UUID, basis_version_id: UUID
    ) -> str:
        provenance = await session.scalar(
            select(SourceProvenanceRecord).where(SourceProvenanceRecord.id == provenance_id)
        )
        if provenance is None:
            raise LegalEffectsImportError(LegalEffectsErrorCode.PROVENANCE_NOT_FOUND)
        if provenance.document_version_id != basis_version_id:
            raise LegalEffectsImportError(LegalEffectsErrorCode.PROVENANCE_VERSION_MISMATCH)
        if provenance.transport_trust_mode != "STRICT_TLS":
            raise LegalEffectsImportError(LegalEffectsErrorCode.PROVENANCE_TRUST_INELIGIBLE)
        return provenance.provenance_type

    async def _resolve_locator(
        self, session: AsyncSession, version_id: UUID, kind: str, value: str
    ) -> None:
        locators = (
            await session.scalars(
                select(DocumentChunk.locator).where(DocumentChunk.document_version_id == version_id)
            )
        ).all()
        if not any(locator_matches(locator, kind, value) for locator in locators):
            raise LegalEffectsImportError(LegalEffectsErrorCode.LOCATOR_INVALID)

    async def _active_assertion_ids(
        self, session: AsyncSession, key: tuple[UUID, UUID, str, str]
    ) -> list[str]:
        subject_id, object_id, relation_kind, effect_state = key
        return list(
            (
                await session.scalars(
                    select(ReviewedLegalEffectAssertion.assertion_id).where(
                        ReviewedLegalEffectAssertion.subject_document_version_id == subject_id,
                        ReviewedLegalEffectAssertion.object_document_version_id == object_id,
                        ReviewedLegalEffectAssertion.relation_kind == relation_kind,
                        ReviewedLegalEffectAssertion.effect_state == effect_state,
                        ~exists().where(
                            ReviewedLegalEffectEvent.assertion_id
                            == ReviewedLegalEffectAssertion.assertion_id
                        ),
                    )
                )
            ).all()
        )

    async def _validate_event(
        self,
        session: AsyncSession,
        event_id: str,
        target_assertion_id: str,
        current_assertions: dict[str, str],
    ) -> None:
        if await session.scalar(
            select(ReviewedLegalEffectEvent.event_id).where(
                ReviewedLegalEffectEvent.event_id == event_id
            )
        ):
            raise LegalEffectsImportError(LegalEffectsErrorCode.EVENT_ID_CONFLICT)
        target_id = current_assertions.get(target_assertion_id, target_assertion_id)
        if target_assertion_id not in current_assertions and not await session.scalar(
            select(ReviewedLegalEffectAssertion.assertion_id).where(
                ReviewedLegalEffectAssertion.assertion_id == target_id
            )
        ):
            raise LegalEffectsImportError(LegalEffectsErrorCode.EVENT_TARGET_NOT_FOUND)
        if await session.scalar(
            select(ReviewedLegalEffectEvent.event_id).where(
                ReviewedLegalEffectEvent.assertion_id == target_id
            )
        ):
            raise LegalEffectsImportError(LegalEffectsErrorCode.EVENT_CONFLICT)
