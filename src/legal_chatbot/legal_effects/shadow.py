"""Read-only, default-disabled synthetic shadow evaluation for reviewed effects."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from legal_chatbot.documents.orm import (
    DocumentChunk,
    DocumentVersion,
    ReviewedLegalEffectAssertion,
    ReviewedLegalEffectEvent,
    ReviewedLegalEffectFamily,
    ReviewedLegalEffectImport,
    SourceProvenanceRecord,
)
from legal_chatbot.legal_effects.validation import locator_matches

_OPAQUE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$")
_PROFILE_VERSION = "reviewed-legal-effects-shadow-v1"


class ReviewedLegalEffectsShadowOutcome(StrEnum):
    SHADOW_DISABLED = "SHADOW_DISABLED"
    SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"
    SHADOW_SUPPRESSED_EVENT = "SHADOW_SUPPRESSED_EVENT"
    SHADOW_UNRESOLVED = "SHADOW_UNRESOLVED"
    SHADOW_CONFLICT = "SHADOW_CONFLICT"
    SHADOW_INPUT_REJECTED = "SHADOW_INPUT_REJECTED"


class ReviewedLegalEffectsManualPolicy(StrEnum):
    """The sole approved Gate-3 manual-evidence policy."""

    HASH_PINNED_PILOT_ALLOWED = "HASH_PINNED_PILOT_ALLOWED"


@dataclass(frozen=True)
class ReviewedLegalEffectsShadowSettings:
    """Explicit server-owned shadow profile; it has no environment/runtime wiring."""

    enabled: bool = False
    manual_policy: ReviewedLegalEffectsManualPolicy = (
        ReviewedLegalEffectsManualPolicy.HASH_PINNED_PILOT_ALLOWED
    )
    profile_version: str = _PROFILE_VERSION


@dataclass(frozen=True)
class ShadowFamilyRef:
    """Server-owned registry scope; callers must not derive it from user/model input."""

    import_id: str = field(repr=False)
    family_id: str = field(repr=False)


@dataclass(frozen=True)
class ReviewedLegalEffectsShadowDiagnostic:
    """Content-free, in-memory-only shadow result with no endpoint/evidence identities."""

    outcome: ReviewedLegalEffectsShadowOutcome
    assertion_count: int = 0
    active_count: int = 0
    corrected_count: int = 0
    revoked_count: int = 0
    unresolved_count: int = 0
    manual_snapshot_basis_count: int = 0
    source_fetch_basis_count: int = 0
    completeness: str | None = None
    manual_snapshot_caveat: bool = False
    profile_version: str = _PROFILE_VERSION
    import_id: str | None = field(default=None, repr=False)
    family_id: str | None = field(default=None, repr=False)

    def to_public_dict(self) -> dict[str, object]:
        """Serialize only aggregate diagnostics, excluding opaque registry identities."""

        return {
            "outcome": self.outcome.value,
            "assertion_count": self.assertion_count,
            "active_count": self.active_count,
            "corrected_count": self.corrected_count,
            "revoked_count": self.revoked_count,
            "unresolved_count": self.unresolved_count,
            "manual_snapshot_basis_count": self.manual_snapshot_basis_count,
            "source_fetch_basis_count": self.source_fetch_basis_count,
            "completeness": self.completeness,
            "manual_snapshot_caveat": self.manual_snapshot_caveat,
            "profile_version": self.profile_version,
        }


class ReviewedLegalEffectsShadowEvaluator:
    """Evaluate a registry family read-only without affecting any product behavior."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: ReviewedLegalEffectsShadowSettings | object,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings

    async def evaluate(self, ref: ShadowFamilyRef | object) -> ReviewedLegalEffectsShadowDiagnostic:
        """Return a bounded diagnostic; disabled evaluation never opens a DB session."""

        if (
            isinstance(self._settings, ReviewedLegalEffectsShadowSettings)
            and not self._settings.enabled
        ):
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_DISABLED)
        if not self._valid_settings() or not self._valid_ref(ref):
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_INPUT_REJECTED)
        assert isinstance(ref, ShadowFamilyRef)
        try:
            async with self._session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    )
                    return await self._evaluate_in_transaction(session, ref)
        except SQLAlchemyError:
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED, ref)
        except Exception:
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED, ref)

    def _valid_settings(self) -> bool:
        return (
            isinstance(self._settings, ReviewedLegalEffectsShadowSettings)
            and self._settings.enabled is True
            and self._settings.manual_policy
            is ReviewedLegalEffectsManualPolicy.HASH_PINNED_PILOT_ALLOWED
            and self._settings.profile_version == _PROFILE_VERSION
        )

    @staticmethod
    def _valid_ref(ref: ShadowFamilyRef | object) -> bool:
        return (
            isinstance(ref, ShadowFamilyRef)
            and _OPAQUE_ID.fullmatch(ref.import_id) is not None
            and _OPAQUE_ID.fullmatch(ref.family_id) is not None
        )

    async def _evaluate_in_transaction(
        self, session: AsyncSession, ref: ShadowFamilyRef
    ) -> ReviewedLegalEffectsShadowDiagnostic:
        family = await session.scalar(
            select(ReviewedLegalEffectFamily).where(
                ReviewedLegalEffectFamily.import_id == ref.import_id,
                ReviewedLegalEffectFamily.family_id == ref.family_id,
                exists().where(ReviewedLegalEffectImport.import_id == ref.import_id),
            )
        )
        if family is None:
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED, ref)
        assertions = list(
            (
                await session.scalars(
                    select(ReviewedLegalEffectAssertion).where(
                        ReviewedLegalEffectAssertion.import_id == ref.import_id,
                        ReviewedLegalEffectAssertion.family_id == ref.family_id,
                    )
                )
            ).all()
        )
        assertion_ids = [assertion.assertion_id for assertion in assertions]
        events = list(
            (
                await session.scalars(
                    select(ReviewedLegalEffectEvent).where(
                        ReviewedLegalEffectEvent.assertion_id.in_(assertion_ids)
                    )
                )
            ).all()
            if assertion_ids
            else []
        )
        event_targets = Counter(event.assertion_id for event in events)
        suppressed_ids = set(event_targets)
        active_assertions = [
            assertion for assertion in assertions if assertion.assertion_id not in suppressed_ids
        ]
        base = {
            "assertion_count": len(assertions),
            "active_count": len(active_assertions),
            "corrected_count": sum(event.event_kind == "CORRECTS" for event in events),
            "revoked_count": sum(event.event_kind == "REVOKES" for event in events),
            "completeness": family.completeness,
        }
        if any(count > 1 for count in event_targets.values()) or self._duplicate_active(
            active_assertions
        ):
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_CONFLICT, ref, **base)

        unresolved_count, manual_count, source_fetch_count = await self._revalidate_active(
            session, active_assertions
        )
        base.update(
            unresolved_count=unresolved_count,
            manual_snapshot_basis_count=manual_count,
            source_fetch_basis_count=source_fetch_count,
            manual_snapshot_caveat=manual_count > 0,
        )
        if unresolved_count:
            return self._diagnostic(
                ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED, ref, **base
            )
        if assertions and not active_assertions and events:
            return self._diagnostic(
                ReviewedLegalEffectsShadowOutcome.SHADOW_SUPPRESSED_EVENT, ref, **base
            )
        if active_assertions:
            return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_ELIGIBLE, ref, **base)
        return self._diagnostic(ReviewedLegalEffectsShadowOutcome.SHADOW_UNRESOLVED, ref, **base)

    @staticmethod
    def _duplicate_active(assertions: list[ReviewedLegalEffectAssertion]) -> bool:
        keys = [
            (
                assertion.subject_document_version_id,
                assertion.object_document_version_id,
                assertion.relation_kind,
                assertion.effect_state,
            )
            for assertion in assertions
        ]
        return len(keys) != len(set(keys))

    async def _revalidate_active(
        self, session: AsyncSession, assertions: list[ReviewedLegalEffectAssertion]
    ) -> tuple[int, int, int]:
        unresolved = 0
        basis_types: dict[UUID, str] = {}
        for assertion in assertions:
            provenance_type = await self._revalidate_assertion(session, assertion)
            if provenance_type is None:
                unresolved += 1
            else:
                basis_types[assertion.basis_source_provenance_record_id] = provenance_type
        return (
            unresolved,
            sum(value == "manual_snapshot" for value in basis_types.values()),
            sum(value == "source_fetch" for value in basis_types.values()),
        )

    async def _revalidate_assertion(
        self, session: AsyncSession, assertion: ReviewedLegalEffectAssertion
    ) -> str | None:
        if assertion.relation_kind not in {"IMPLEMENTS", "GOVERNS"}:
            return None
        if assertion.effect_state != "EFFECT_NOT_MODELED":
            return None
        versions = []
        for version_id in (
            assertion.subject_document_version_id,
            assertion.object_document_version_id,
            assertion.basis_document_version_id,
        ):
            version = await session.get(DocumentVersion, version_id)
            if version is None or not await self._has_strict_provenance(session, version.id):
                return None
            versions.append(version)
        provenance = await session.get(
            SourceProvenanceRecord, assertion.basis_source_provenance_record_id
        )
        if (
            provenance is None
            or provenance.document_version_id != versions[2].id
            or provenance.transport_trust_mode != "STRICT_TLS"
        ):
            return None
        locators = (
            await session.scalars(
                select(DocumentChunk.locator).where(
                    DocumentChunk.document_version_id == versions[2].id
                )
            )
        ).all()
        if not any(
            locator_matches(locator, assertion.basis_locator_type, assertion.basis_locator_value)
            for locator in locators
        ):
            return None
        return provenance.provenance_type

    @staticmethod
    async def _has_strict_provenance(session: AsyncSession, version_id: UUID) -> bool:
        return bool(
            await session.scalar(
                select(
                    exists().where(
                        SourceProvenanceRecord.document_version_id == version_id,
                        SourceProvenanceRecord.transport_trust_mode == "STRICT_TLS",
                    )
                )
            )
        )

    def _diagnostic(
        self,
        outcome: ReviewedLegalEffectsShadowOutcome,
        ref: ShadowFamilyRef | None = None,
        **counts: Any,
    ) -> ReviewedLegalEffectsShadowDiagnostic:
        profile_version = (
            self._settings.profile_version
            if isinstance(self._settings, ReviewedLegalEffectsShadowSettings)
            else _PROFILE_VERSION
        )
        return ReviewedLegalEffectsShadowDiagnostic(
            outcome=outcome,
            profile_version=profile_version,
            import_id=ref.import_id if ref is not None else None,
            family_id=ref.family_id if ref is not None else None,
            **counts,
        )
