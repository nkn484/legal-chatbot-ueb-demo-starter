"""Add immutable transport-trust provenance and retrieval trust scope.

Revision ID: 0006_tls_trust_provenance
Revises: 0005_channel_delivery
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006_tls_trust_provenance"
down_revision = "0005_channel_delivery"
branch_labels = None
depends_on = None

_PROVENANCE_TABLE = "source_provenance_records"


def upgrade() -> None:
    op.add_column(
        _PROVENANCE_TABLE,
        sa.Column("transport_trust_mode", sa.String(length=48), nullable=True),
    )
    op.add_column(_PROVENANCE_TABLE, sa.Column("tls_chain_verified", sa.Boolean(), nullable=True))
    op.add_column(
        _PROVENANCE_TABLE, sa.Column("tls_hostname_verified", sa.Boolean(), nullable=True)
    )
    op.add_column(_PROVENANCE_TABLE, sa.Column("trust_exception_id", sa.String(length=128)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("trust_exception_digest", sa.CHAR(length=64)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("policy_id", sa.String(length=128)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("policy_version", sa.Integer()))
    op.add_column(_PROVENANCE_TABLE, sa.Column("compiled_policy_digest", sa.CHAR(length=64)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("registry_snapshot_digest", sa.CHAR(length=64)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("pin_set_id", sa.String(length=128)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("pin_set_version", sa.Integer()))
    op.add_column(_PROVENANCE_TABLE, sa.Column("pin_set_digest", sa.CHAR(length=64)))
    op.add_column(_PROVENANCE_TABLE, sa.Column("matched_pin_id", sa.String(length=128)))
    op.add_column(
        _PROVENANCE_TABLE,
        sa.Column("peer_certificate_not_before", sa.DateTime(timezone=True)),
    )
    op.add_column(
        _PROVENANCE_TABLE,
        sa.Column("peer_certificate_not_after", sa.DateTime(timezone=True)),
    )
    op.add_column(_PROVENANCE_TABLE, sa.Column("acquisition_correlation_id", sa.String(length=128)))

    op.execute(
        "UPDATE source_provenance_records SET "
        "transport_trust_mode = CASE WHEN tls_verified THEN 'STRICT_TLS' "
        "ELSE 'LEGACY_UNVERIFIED' END, "
        "tls_chain_verified = tls_verified, tls_hostname_verified = tls_verified"
    )
    op.alter_column(_PROVENANCE_TABLE, "transport_trust_mode", nullable=False)
    op.alter_column(_PROVENANCE_TABLE, "tls_chain_verified", nullable=False)
    op.alter_column(_PROVENANCE_TABLE, "tls_hostname_verified", nullable=False)
    op.create_check_constraint(
        "ck_source_provenance_records_transport_trust_mode",
        _PROVENANCE_TABLE,
        "transport_trust_mode IN "
        "('STRICT_TLS', 'USER_APPROVED_TOFU_PINNED_EXCEPTION', 'LEGACY_UNVERIFIED')",
    )
    op.create_check_constraint(
        "ck_source_provenance_records_tls_verified_compatibility",
        _PROVENANCE_TABLE,
        "tls_verified = (tls_chain_verified AND tls_hostname_verified)",
    )
    op.create_check_constraint(
        "ck_source_provenance_records_policy_metadata_shape",
        _PROVENANCE_TABLE,
        "(policy_id IS NULL AND policy_version IS NULL AND compiled_policy_digest IS NULL "
        "AND registry_snapshot_digest IS NULL) OR "
        "(policy_id IS NOT NULL AND policy_version IS NOT NULL "
        "AND compiled_policy_digest IS NOT NULL AND registry_snapshot_digest IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_source_provenance_records_trust_identity_format",
        _PROVENANCE_TABLE,
        "(trust_exception_id IS NULL OR trust_exception_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
        "AND (policy_id IS NULL OR policy_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
        "AND (pin_set_id IS NULL OR pin_set_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
        "AND (matched_pin_id IS NULL OR matched_pin_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
        "AND (acquisition_correlation_id IS NULL OR "
        "acquisition_correlation_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') "
        "AND (policy_version IS NULL OR policy_version > 0) "
        "AND (pin_set_version IS NULL OR pin_set_version > 0)",
    )
    op.create_check_constraint(
        "ck_source_provenance_records_transport_trust_shape",
        _PROVENANCE_TABLE,
        "(transport_trust_mode = 'STRICT_TLS' "
        "AND tls_chain_verified AND tls_hostname_verified AND tls_verified "
        "AND trust_exception_id IS NULL AND trust_exception_digest IS NULL "
        "AND pin_set_id IS NULL AND pin_set_version IS NULL AND pin_set_digest IS NULL "
        "AND matched_pin_id IS NULL AND peer_certificate_not_before IS NULL "
        "AND peer_certificate_not_after IS NULL) OR "
        "(transport_trust_mode = 'USER_APPROVED_TOFU_PINNED_EXCEPTION' "
        "AND tls_chain_verified AND NOT tls_hostname_verified AND NOT tls_verified "
        "AND trust_exception_id IS NOT NULL AND trust_exception_digest IS NOT NULL "
        "AND policy_id IS NOT NULL AND policy_version IS NOT NULL "
        "AND compiled_policy_digest IS NOT NULL AND registry_snapshot_digest IS NOT NULL "
        "AND pin_set_id IS NOT NULL AND pin_set_version IS NOT NULL AND pin_set_digest IS NOT NULL "
        "AND matched_pin_id IS NOT NULL AND peer_certificate_not_before IS NOT NULL "
        "AND peer_certificate_not_after IS NOT NULL "
        "AND peer_certificate_not_before <= peer_certificate_not_after "
        "AND acquisition_correlation_id IS NOT NULL) OR "
        "(transport_trust_mode = 'LEGACY_UNVERIFIED' "
        "AND NOT tls_chain_verified AND NOT tls_hostname_verified AND NOT tls_verified "
        "AND trust_exception_id IS NULL AND trust_exception_digest IS NULL "
        "AND policy_id IS NULL AND policy_version IS NULL AND compiled_policy_digest IS NULL "
        "AND registry_snapshot_digest IS NULL AND pin_set_id IS NULL AND pin_set_version IS NULL "
        "AND pin_set_digest IS NULL AND matched_pin_id IS NULL "
        "AND peer_certificate_not_before IS NULL AND peer_certificate_not_after IS NULL "
        "AND acquisition_correlation_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_source_provenance_records_trust_digests",
        _PROVENANCE_TABLE,
        "(trust_exception_digest IS NULL OR trust_exception_digest ~ '^[0-9a-f]{64}$') "
        "AND (compiled_policy_digest IS NULL OR compiled_policy_digest ~ '^[0-9a-f]{64}$') "
        "AND (registry_snapshot_digest IS NULL OR registry_snapshot_digest ~ '^[0-9a-f]{64}$') "
        "AND (pin_set_digest IS NULL OR pin_set_digest ~ '^[0-9a-f]{64}$')",
    )
    op.create_index(
        "ix_source_provenance_records_trust_mode", _PROVENANCE_TABLE, ["transport_trust_mode"]
    )
    op.create_index(
        "ix_source_provenance_records_policy_identity",
        _PROVENANCE_TABLE,
        ["policy_id", "policy_version"],
    )

    op.add_column(
        "retrieval_runs",
        sa.Column(
            "trust_scope",
            sa.String(length=32),
            server_default=sa.text("'STRICT_TLS_ONLY'"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE retrieval_runs SET trust_scope = 'STRICT_TLS_ONLY' WHERE trust_scope IS NULL"
    )
    op.create_index("ix_retrieval_runs_trust_scope", "retrieval_runs", ["trust_scope"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_runs_trust_scope", table_name="retrieval_runs")
    op.drop_column("retrieval_runs", "trust_scope")

    op.drop_index("ix_source_provenance_records_policy_identity", table_name=_PROVENANCE_TABLE)
    op.drop_index("ix_source_provenance_records_trust_mode", table_name=_PROVENANCE_TABLE)
    op.drop_constraint(
        "ck_source_provenance_records_trust_digests", _PROVENANCE_TABLE, type_="check"
    )
    op.drop_constraint(
        "ck_source_provenance_records_transport_trust_shape", _PROVENANCE_TABLE, type_="check"
    )
    op.drop_constraint(
        "ck_source_provenance_records_policy_metadata_shape", _PROVENANCE_TABLE, type_="check"
    )
    op.drop_constraint(
        "ck_source_provenance_records_trust_identity_format", _PROVENANCE_TABLE, type_="check"
    )
    op.drop_constraint(
        "ck_source_provenance_records_tls_verified_compatibility", _PROVENANCE_TABLE, type_="check"
    )
    op.drop_constraint(
        "ck_source_provenance_records_transport_trust_mode", _PROVENANCE_TABLE, type_="check"
    )
    for column_name in (
        "acquisition_correlation_id",
        "peer_certificate_not_after",
        "peer_certificate_not_before",
        "matched_pin_id",
        "pin_set_digest",
        "pin_set_version",
        "pin_set_id",
        "registry_snapshot_digest",
        "compiled_policy_digest",
        "policy_version",
        "policy_id",
        "trust_exception_digest",
        "trust_exception_id",
        "tls_hostname_verified",
        "tls_chain_verified",
        "transport_trust_mode",
    ):
        op.drop_column(_PROVENANCE_TABLE, column_name)
