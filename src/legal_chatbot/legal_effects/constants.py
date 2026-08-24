"""Closed vocabulary for the approved reviewed-legal-effects v1 artifact."""

from enum import StrEnum

SCHEMA_VERSION = "reviewed-legal-effects-v1"
PROFILE_STATE = "APPROVED_SCHEMA_DEFAULT_OFF"
MAX_ARTIFACT_BYTES = 1_048_576
MAX_FAMILIES = 100
MAX_RELATIONS = 1_000
MAX_EVENTS = 1_000
MAX_OPAQUE_ID_LENGTH = 128
MAX_EXTERNAL_ID_LENGTH = 256
MAX_NOTE_LENGTH = 500


class SourceId(StrEnum):
    """Approved source IDs eligible for reviewed artifact endpoints."""

    VBQPPL = "VBQPPL"
    VNU = "VNU"
    UEB = "UEB"


class RelationKind(StrEnum):
    """Reviewed relation kinds accepted in v1."""

    IMPLEMENTS = "IMPLEMENTS"
    GOVERNS = "GOVERNS"


class EffectState(StrEnum):
    """The v1 profile deliberately does not model legal effect or time."""

    EFFECT_NOT_MODELED = "EFFECT_NOT_MODELED"


class LocatorKind(StrEnum):
    """Pinpoint locator kinds accepted in v1."""

    ARTICLE = "ARTICLE"
    CLAUSE = "CLAUSE"
    SECTION = "SECTION"
    PAGE = "PAGE"


class FamilyCompleteness(StrEnum):
    """Bounded declaration of the reviewed family scope."""

    DECLARED_PARTIAL = "DECLARED_PARTIAL"
    DECLARED_COMPLETE = "DECLARED_COMPLETE"


class CorrectionEventKind(StrEnum):
    """Append-only correction actions represented by an artifact event."""

    CORRECTS = "CORRECTS"
    REVOKES = "REVOKES"


class CorrectionReasonCode(StrEnum):
    """Approved append-only correction reason codes aligned to the future DB enum."""

    ENDPOINT_NOT_FOUND = "ENDPOINT_NOT_FOUND"
    VERSION_HASH_MISMATCH = "VERSION_HASH_MISMATCH"
    PROVENANCE_NOT_FOUND = "PROVENANCE_NOT_FOUND"
    LOCATOR_INVALID = "LOCATOR_INVALID"
    DUPLICATE_ASSERTION = "DUPLICATE_ASSERTION"
    FAMILY_SCOPE_CONFLICT = "FAMILY_SCOPE_CONFLICT"
    REVIEW_DISAGREEMENT = "REVIEW_DISAGREEMENT"
    SUPERSEDED_BY_REVIEW = "SUPERSEDED_BY_REVIEW"
    WITHDRAWN_BY_REVIEW = "WITHDRAWN_BY_REVIEW"
