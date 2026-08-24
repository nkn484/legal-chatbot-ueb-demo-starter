"""Source-neutral immutable legal document, provenance, and health contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SourceHealthStatus(StrEnum):
    """Availability states exposed by a source health probe."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class ProvenanceType(StrEnum):
    """Kinds of evidence provenance supported by the source boundary."""

    SOURCE_FETCH = "source_fetch"
    MANUAL_SNAPSHOT = "manual_snapshot"


class TransportTrustMode(StrEnum):
    """Immutable transport trust classification; only strict TLS is normally eligible."""

    STRICT_TLS = "STRICT_TLS"
    USER_APPROVED_TOFU_PINNED_EXCEPTION = "USER_APPROVED_TOFU_PINNED_EXCEPTION"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


class SourceErrorCode(StrEnum):
    """Stable source failure categories safe for callers and logs."""

    SOURCE_NOT_CONFIGURED = "source_not_configured"
    SOURCE_NOT_IMPLEMENTED = "source_not_implemented"
    ACCESS_DENIED = "access_denied"
    DOCUMENT_NOT_ALLOWED = "document_not_allowed"
    DOCUMENT_NOT_FOUND = "document_not_found"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    PROVENANCE_MISMATCH = "provenance_mismatch"


class _FrozenSourceModel(BaseModel):
    model_config = ConfigDict(frozen=True)


def _timezone_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class SourceDocumentRef(_FrozenSourceModel):
    """A source-owned, externally resolvable document identifier."""

    source_id: str = Field(min_length=1, max_length=32)
    external_id: str = Field(min_length=1, max_length=256)
    document_number: str | None = Field(default=None, min_length=1, max_length=256)
    canonical_url: str | None = Field(default=None, min_length=1, max_length=2_048)


class DiscoveryRequest(_FrozenSourceModel):
    """An exact-number discovery request authorized by the trusted manifest."""

    source_id: str = Field(min_length=1, max_length=32)
    document_number: str = Field(min_length=1, max_length=256)
    transport: str = Field(pattern=r"^SOAP$")


class DiscoveryCandidate(_FrozenSourceModel):
    """Sanitized discovery output for review; it is not a fetch capability."""

    source_id: str = Field(min_length=1, max_length=32)
    document_number: str = Field(min_length=1, max_length=256)
    external_id: str = Field(min_length=1, max_length=256)
    transport: str = Field(pattern=r"^SOAP$")


class FetchApprovedDocumentRef(SourceDocumentRef):
    """A transport-specific immutable reference derived from a fetch-approved manifest entry."""

    transport: str = Field(min_length=1, max_length=64)
    detail_path: str = Field(pattern=r"^/[^?#]*$")
    operation: str = Field(min_length=1, max_length=128)


class SourceProvenance(_FrozenSourceModel):
    """Metadata proving how a document snapshot was obtained."""

    provenance_type: ProvenanceType
    source_id: str = Field(min_length=1, max_length=32)
    transport: str = Field(min_length=1, max_length=64)
    operation: str = Field(min_length=1, max_length=128)
    retrieved_at: datetime
    canonical_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    tls_verified: bool
    transport_trust_mode: TransportTrustMode | None = None
    tls_chain_verified: bool | None = None
    tls_hostname_verified: bool | None = None
    trust_exception_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )
    trust_exception_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    policy_version: int | None = Field(default=None, ge=1, le=2_147_483_647)
    compiled_policy_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    registry_snapshot_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    pin_set_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    pin_set_version: int | None = Field(default=None, ge=1, le=2_147_483_647)
    pin_set_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    matched_pin_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    peer_certificate_not_before: datetime | None = None
    peer_certificate_not_after: datetime | None = None
    acquisition_correlation_id: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    )

    _validate_provenance_timestamps = field_validator(
        "retrieved_at", "peer_certificate_not_before", "peer_certificate_not_after"
    )(_timezone_aware)

    @model_validator(mode="after")
    def validate_transport_trust(self) -> "SourceProvenance":
        """Derive legacy fields and fail closed on trust/provenance shape mismatches."""

        mode = self.transport_trust_mode
        if mode is None:
            mode = (
                TransportTrustMode.STRICT_TLS
                if self.tls_verified
                else TransportTrustMode.LEGACY_UNVERIFIED
            )
            object.__setattr__(self, "transport_trust_mode", mode)

        if self.tls_chain_verified is None:
            object.__setattr__(
                self,
                "tls_chain_verified",
                mode is TransportTrustMode.STRICT_TLS,
            )
        if self.tls_hostname_verified is None:
            object.__setattr__(
                self,
                "tls_hostname_verified",
                mode is TransportTrustMode.STRICT_TLS,
            )
        if self.tls_verified != (self.tls_chain_verified and self.tls_hostname_verified):
            raise ValueError("tls_verified must equal tls_chain_verified AND tls_hostname_verified")

        exception_metadata = (self.trust_exception_id, self.trust_exception_digest)
        policy_metadata = (
            self.policy_id,
            self.policy_version,
            self.compiled_policy_digest,
            self.registry_snapshot_digest,
        )
        pin_metadata = (
            self.pin_set_id,
            self.pin_set_version,
            self.pin_set_digest,
            self.matched_pin_id,
        )
        certificate_metadata = (self.peer_certificate_not_before, self.peer_certificate_not_after)
        if self.peer_certificate_not_before and self.peer_certificate_not_after:
            if self.peer_certificate_not_before > self.peer_certificate_not_after:
                raise ValueError("peer certificate validity interval is inverted")
        if any(policy_metadata) and not all(policy_metadata):
            raise ValueError("policy trust metadata must be complete when present")

        if mode is TransportTrustMode.STRICT_TLS:
            if not (self.tls_chain_verified and self.tls_hostname_verified and self.tls_verified):
                raise ValueError("STRICT_TLS requires verified chain and hostname")
            if any(exception_metadata) or any(pin_metadata) or any(certificate_metadata):
                raise ValueError("STRICT_TLS does not permit exception or pin metadata")
        elif mode is TransportTrustMode.USER_APPROVED_TOFU_PINNED_EXCEPTION:
            if self.tls_chain_verified is not True or self.tls_hostname_verified is not False:
                raise ValueError("TOFU exception requires verified chain and unverified hostname")
            if self.tls_verified:
                raise ValueError("TOFU exception must retain tls_verified=false")
            if not all(
                (*exception_metadata, *policy_metadata, *pin_metadata, *certificate_metadata)
            ):
                raise ValueError(
                    "TOFU exception requires complete trust, policy, pin, and certificate metadata"
                )
            if self.acquisition_correlation_id is None:
                raise ValueError("TOFU exception requires acquisition_correlation_id")
        elif mode is TransportTrustMode.LEGACY_UNVERIFIED:
            if self.tls_chain_verified or self.tls_hostname_verified or self.tls_verified:
                raise ValueError("LEGACY_UNVERIFIED requires unverified chain and hostname")
            if any((*exception_metadata, *policy_metadata, *pin_metadata, *certificate_metadata)):
                raise ValueError("LEGACY_UNVERIFIED does not permit trust exception metadata")
            if self.acquisition_correlation_id is not None:
                raise ValueError("LEGACY_UNVERIFIED does not permit acquisition metadata")
        return self


class LegalDocumentSnapshot(_FrozenSourceModel):
    """Retrieved legal document content with immutable source provenance."""

    source_id: str = Field(min_length=1, max_length=32)
    external_id: str = Field(min_length=1, max_length=256)
    document_number: str | None = Field(default=None, min_length=1, max_length=256)
    title: str | None = Field(default=None, min_length=1, max_length=4_096)
    document_type: str | None = Field(default=None, min_length=1, max_length=512)
    issuing_authority: str | None = Field(default=None, min_length=1, max_length=1_024)
    issue_date: datetime | None = None
    effective_date: datetime | None = None
    source_updated_at: datetime | None = None
    legal_status: str | None = Field(default=None, min_length=1, max_length=256)
    canonical_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    content_html: str = Field(min_length=1, max_length=2_097_152)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: SourceProvenance

    _validate_dates = field_validator("issue_date", "effective_date", "source_updated_at")(
        _timezone_aware
    )

    @model_validator(mode="after")
    def validate_provenance_identity(self) -> "LegalDocumentSnapshot":
        """Keep source identity and canonical URL bound to the retrieval provenance."""

        if self.source_id != self.provenance.source_id:
            raise ValueError("snapshot source_id must match provenance source_id")
        if (
            self.canonical_url is not None
            and self.provenance.canonical_url is not None
            and self.canonical_url != self.provenance.canonical_url
        ):
            raise ValueError("snapshot canonical_url must match provenance canonical_url")
        return self


class SourceHealth(_FrozenSourceModel):
    """Normalized result of a source health check."""

    status: SourceHealthStatus
    source_id: str = Field(min_length=1, max_length=32)
    transport: str = Field(min_length=1, max_length=64)
    duration_ms: float = Field(ge=0)
    error_code: SourceErrorCode | None = None
