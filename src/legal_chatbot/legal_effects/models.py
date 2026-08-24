"""Frozen Pydantic v2 models for the approved reviewed-legal-effects v1 artifact."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from legal_chatbot.legal_effects.constants import (
    MAX_EVENTS,
    MAX_EXTERNAL_ID_LENGTH,
    MAX_FAMILIES,
    MAX_NOTE_LENGTH,
    MAX_OPAQUE_ID_LENGTH,
    MAX_RELATIONS,
    CorrectionEventKind,
    CorrectionReasonCode,
    FamilyCompleteness,
    LocatorKind,
    RelationKind,
    SourceId,
)

OPAQUE_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9._:-]{0,127}$"
EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
URL_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
CANONICAL_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


class _FrozenArtifactModel(BaseModel):
    """Base model that rejects undeclared fields and cannot be mutated."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_safe_text(value: str) -> str:
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("text contains control characters")
    if URL_PATTERN.search(value):
        raise ValueError("text contains a URL")
    return value


def _require_timezone_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


class Endpoint(_FrozenArtifactModel):
    """A stable source/external identity pinned to immutable version hashes."""

    source_id: SourceId = Field(repr=False)
    external_id: str = Field(
        min_length=1,
        max_length=MAX_EXTERNAL_ID_LENGTH,
        pattern=EXTERNAL_ID_PATTERN,
        repr=False,
    )
    snapshot_sha256: str = Field(
        pattern=SHA256_PATTERN, min_length=64, max_length=64, repr=False
    )
    normalized_text_sha256: str = Field(
        pattern=SHA256_PATTERN, min_length=64, max_length=64, repr=False
    )


class Locator(_FrozenArtifactModel):
    """A bounded, safe legal pinpoint without source text or URLs."""

    kind: LocatorKind
    value: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)

    _validate_value = field_validator("value")(_require_safe_text)


class Basis(_FrozenArtifactModel):
    """Evidence version, provenance record, and pinpoint supporting a relation."""

    endpoint: Endpoint
    provenance_id: UUID = Field(repr=False)
    locator: Locator

    @field_validator("provenance_id", mode="before")
    @classmethod
    def validate_canonical_provenance_id(cls, value: object) -> object:
        """Accept only canonical UUID strings (or a UUID supplied by an in-memory caller)."""

        if isinstance(value, UUID):
            return value
        if not isinstance(value, str) or CANONICAL_UUID_PATTERN.fullmatch(value) is None:
            raise ValueError("provenance ID must be a canonical UUID")
        return value


class Approval(_FrozenArtifactModel):
    """Global review and independent approval metadata inherited by every event."""

    submitted_by: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    submitted_at: datetime
    reviewer_role: Literal["LEGAL_REVIEWER"]
    reviewed_by: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    reviewed_at: datetime
    approver_role: Literal["LEGAL_APPROVER"]
    approved_by: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    approved_at: datetime

    _validate_timestamps = field_validator("submitted_at", "reviewed_at", "approved_at")(
        _require_timezone_aware
    )

    @model_validator(mode="after")
    def validate_order_and_independence(self) -> Self:
        """Require ordered approval actions and independent reviewer/approver identities."""

        if not self.submitted_at <= self.reviewed_at <= self.approved_at:
            raise ValueError("approval timestamps must be ordered")
        if self.reviewed_by == self.approved_by:
            raise ValueError("reviewer and approver must differ")
        return self


class Family(_FrozenArtifactModel):
    """A generic reviewed family declaration with bounded completeness language."""

    family_id: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    completeness: FamilyCompleteness
    scope_note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)

    _validate_scope_note = field_validator("scope_note")(_require_safe_text)


class Relation(_FrozenArtifactModel):
    """A reviewed relation assertion; v1 deliberately has no temporal interval."""

    relation_id: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    family_id: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    subject: Endpoint
    object: Endpoint
    relation_kind: RelationKind
    effect_state: Literal["EFFECT_NOT_MODELED"]
    basis: Basis

    @model_validator(mode="after")
    def validate_distinct_endpoints(self) -> Self:
        """Forbid assertions whose subject and object select the same evidence version."""

        if self.subject == self.object:
            raise ValueError("subject and object must differ")
        return self


class CorrectionEvent(_FrozenArtifactModel):
    """An optional event inheriting the artifact's global approval metadata."""

    event_id: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    assertion_id: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    kind: CorrectionEventKind
    successor_relation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    reason_code: CorrectionReasonCode
    reason_note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)

    _validate_reason_note = field_validator("reason_note")(_require_safe_text)

    @model_validator(mode="after")
    def validate_correction_shape(self) -> Self:
        """Require a successor only for corrections, never for revocations."""

        if self.kind is CorrectionEventKind.CORRECTS:
            if self.successor_relation_id is None:
                raise ValueError("correction requires a successor relation")
            if self.successor_relation_id == self.assertion_id:
                raise ValueError("correction successor must differ from assertion")
        elif self.successor_relation_id is not None:
            raise ValueError("revocation must not have a successor relation")
        return self


class ReviewedLegalEffectsArtifact(_FrozenArtifactModel):
    """The approved default-off artifact, independent of persistence or runtime behavior."""

    schema_version: Literal["reviewed-legal-effects-v1"]
    profile_state: Literal["APPROVED_SCHEMA_DEFAULT_OFF"]
    artifact_id: str = Field(
        min_length=1,
        max_length=MAX_OPAQUE_ID_LENGTH,
        pattern=OPAQUE_ID_PATTERN,
    )
    approval: Approval
    families: tuple[Family, ...] = Field(min_length=1, max_length=MAX_FAMILIES)
    relations: tuple[Relation, ...] = Field(min_length=1, max_length=MAX_RELATIONS)
    events: tuple[CorrectionEvent, ...] = Field(default=(), max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def validate_references_and_uniqueness(self) -> Self:
        """Apply cross-record integrity checks not expressible by static JSON Schema."""

        family_ids = [family.family_id for family in self.families]
        relation_ids = [relation.relation_id for relation in self.relations]
        event_ids = [event.event_id for event in self.events]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("family IDs must be unique")
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("relation IDs must be unique")
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("event IDs must be unique")

        known_families = set(family_ids)
        known_relations = set(relation_ids)
        if any(relation.family_id not in known_families for relation in self.relations):
            raise ValueError("relation family reference is invalid")

        logical_keys = [
            (relation.family_id, relation.subject, relation.object, relation.relation_kind)
            for relation in self.relations
        ]
        if len(logical_keys) != len(set(logical_keys)):
            raise ValueError("logical relation assertions must be unique")

        event_assertions = [event.assertion_id for event in self.events]
        if len(event_assertions) != len(set(event_assertions)):
            raise ValueError("only one event may target each relation")
        for event in self.events:
            if (
                event.successor_relation_id is not None
                and event.successor_relation_id not in known_relations
            ):
                raise ValueError("event successor reference is invalid")
        return self
