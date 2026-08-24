"""Safe code-only errors for reviewed legal-effects artifact parsing and import."""

from enum import StrEnum


class LegalEffectsErrorCode(StrEnum):
    """Stable error categories that never expose artifact data."""

    ARTIFACT_TOO_LARGE = "artifact_too_large"
    UNSUPPORTED_INPUT = "unsupported_input"
    INVALID_JSON = "invalid_json"
    DUPLICATE_JSON_KEY = "duplicate_json_key"
    INVALID_ARTIFACT = "invalid_artifact"
    INVALID_IMPORTED_BY = "invalid_imported_by"
    ENDPOINT_NOT_FOUND = "endpoint_not_found"
    VERSION_HASH_MISMATCH = "version_hash_mismatch"
    ENDPOINT_AMBIGUOUS = "endpoint_ambiguous"
    PROVENANCE_NOT_FOUND = "provenance_not_found"
    PROVENANCE_VERSION_MISMATCH = "provenance_version_mismatch"
    PROVENANCE_TRUST_INELIGIBLE = "provenance_trust_ineligible"
    LOCATOR_INVALID = "locator_invalid"
    IMPORT_ID_CONFLICT = "import_id_conflict"
    ARTIFACT_HASH_CONFLICT = "artifact_hash_conflict"
    APPROVAL_TIMESTAMP_FUTURE = "approval_timestamp_future"
    EVENT_TARGET_NOT_FOUND = "event_target_not_found"
    EVENT_CONFLICT = "event_conflict"
    EVENT_ID_CONFLICT = "event_id_conflict"
    DUPLICATE_ASSERTION = "duplicate_assertion"
    PERSISTENCE_FAILURE = "persistence_failure"


class LegalEffectsArtifactError(ValueError):
    """A parser failure whose string representation contains only a stable code."""

    def __init__(self, code: LegalEffectsErrorCode) -> None:
        self.code = code
        super().__init__(code.value)

    def __str__(self) -> str:
        return self.code.value


class LegalEffectsImportError(ValueError):
    """An importer failure whose string representation contains only a stable code."""

    def __init__(self, code: LegalEffectsErrorCode) -> None:
        self.code = code
        super().__init__(code.value)

    def __str__(self) -> str:
        return self.code.value
