"""initial schema

Revision ID: 20250115000000
Revises:
Create Date: 2025-01-15 00:00:00.000000+00:00

Creates the four core tables for the Intelligent RBAC Policy Auditor:

    datasets     — ingested Azure AD role-assignment snapshots
    audits       — audit run records linked to a dataset
    findings     — individual security findings produced by an audit
    query_logs   — natural-language query records linked to a dataset

Enum types created:

    audit_status      — pending | running | completed | failed
    finding_category  — overprivileged | dormant_privileged
    finding_severity  — critical | high | medium | low

All UUID primary keys rely on PostgreSQL's ``gen_random_uuid()`` as the
server-side default so that rows inserted outside the ORM still receive
a valid UUID without application involvement.

Indexes created:

    ix_audits_dataset_id     — accelerates FK lookups from audits → datasets
    ix_audits_status         — accelerates polling queries filtered by status
    ix_findings_audit_id     — accelerates FK lookups from findings → audits
    ix_findings_category     — accelerates filtering findings by category
    ix_findings_severity     — accelerates filtering findings by severity
    ix_query_logs_dataset_id — accelerates FK lookups from query_logs → datasets
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Revision identifiers — used by Alembic to order the migration chain.
# ---------------------------------------------------------------------------

revision: str = "20250115000000"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


# ---------------------------------------------------------------------------
# Enum type helpers
# ---------------------------------------------------------------------------

# These ENUM objects are used in table column definitions below.  We set
# create_type=False because the enums are created explicitly via raw SQL in
# the upgrade() function using a DO … EXCEPTION block that is idempotent on
# re-entrant runs (e.g. a retry after a partially-applied migration).

audit_status_enum = postgresql.ENUM(
    "pending",
    "running",
    "completed",
    "failed",
    name="audit_status",
    create_type=False,
)

finding_category_enum = postgresql.ENUM(
    "overprivileged",
    "dormant_privileged",
    name="finding_category",
    create_type=False,
)

finding_severity_enum = postgresql.ENUM(
    "critical",
    "high",
    "medium",
    "low",
    name="finding_severity",
    create_type=False,
)


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Create enum types, all four tables, and supporting indexes."""

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    # Each CREATE TYPE is wrapped in a DO block that swallows
    # duplicate_object errors so the migration is safely re-entrant.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE audit_status AS ENUM (
                'pending', 'running', 'completed', 'failed'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE finding_category AS ENUM (
                'overprivileged', 'dormant_privileged'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE finding_severity AS ENUM (
                'critical', 'high', 'medium', 'low'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """)

    # ------------------------------------------------------------------
    # datasets
    # ------------------------------------------------------------------
    op.create_table(
        "datasets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="Unique dataset identifier (UUIDv4).",
        ),
        sa.Column(
            "name",
            sa.String(255),
            nullable=False,
            comment="Human-readable dataset label.",
        ),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="Full JSON payload as ingested from the caller.",
        ),
        sa.Column(
            "user_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            comment="Number of principals in the dataset.",
        ),
        sa.Column(
            "role_count",
            sa.Integer(),
            nullable=True,
            comment="Number of distinct roles referenced in the dataset.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of dataset ingestion.",
        ),
    )

    # ------------------------------------------------------------------
    # audits
    # ------------------------------------------------------------------
    op.create_table(
        "audits",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="Unique audit identifier (UUIDv4).",
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
            comment="Foreign key to the dataset snapshot this audit analyses.",
        ),
        sa.Column(
            "status",
            audit_status_enum,
            nullable=False,
            server_default="pending",
            comment="Current lifecycle state (pending/running/completed/failed).",
        ),
        sa.Column(
            "parameters",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="Caller-supplied audit configuration overrides stored as JSONB.",
        ),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Aggregate finding statistics written by the pipeline on completion.",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the audit pipeline began processing.",
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="UTC timestamp when the audit pipeline terminated (success or failure).",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of audit record creation.",
        ),
    )

    op.create_index(
        "ix_audits_dataset_id",
        "audits",
        ["dataset_id"],
    )
    op.create_index(
        "ix_audits_status",
        "audits",
        ["status"],
    )

    # ------------------------------------------------------------------
    # findings
    # ------------------------------------------------------------------
    op.create_table(
        "findings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="Unique finding identifier (UUIDv4).",
        ),
        sa.Column(
            "audit_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("audits.id", ondelete="CASCADE"),
            nullable=False,
            comment="Foreign key to the parent audit run.",
        ),
        sa.Column(
            "category",
            finding_category_enum,
            nullable=False,
            comment="Finding category (overprivileged or dormant_privileged).",
        ),
        sa.Column(
            "severity",
            finding_severity_enum,
            nullable=False,
            comment="Risk severity tier (critical/high/medium/low).",
        ),
        sa.Column(
            "principal_id",
            sa.String(255),
            nullable=False,
            comment="Azure AD object ID of the affected principal.",
        ),
        sa.Column(
            "principal_name",
            sa.String(255),
            nullable=False,
            comment="Display name of the affected principal.",
        ),
        sa.Column(
            "principal_type",
            sa.String(64),
            nullable=False,
            comment="Principal type: user, service_principal, or group.",
        ),
        sa.Column(
            "role_assignments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'"),
            comment="JSON array of role assignment objects relevant to this finding.",
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
            comment="Supporting evidence signals (days since sign-in, role counts, etc.).",
        ),
        sa.Column(
            "remediation",
            sa.Text(),
            nullable=False,
            comment="Recommended remediation action in plain language.",
        ),
        sa.Column(
            "narrative",
            sa.Text(),
            nullable=False,
            comment="LLM-generated plain-language explanation of the finding and its risk.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of finding creation.",
        ),
    )

    op.create_index(
        "ix_findings_audit_id",
        "findings",
        ["audit_id"],
    )
    op.create_index(
        "ix_findings_category",
        "findings",
        ["category"],
    )
    op.create_index(
        "ix_findings_severity",
        "findings",
        ["severity"],
    )

    # ------------------------------------------------------------------
    # query_logs
    # ------------------------------------------------------------------
    op.create_table(
        "query_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            comment="Unique query log identifier (UUIDv4).",
        ),
        sa.Column(
            "dataset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("datasets.id", ondelete="CASCADE"),
            nullable=False,
            comment="Foreign key to the dataset snapshot this query was issued against.",
        ),
        sa.Column(
            "question",
            sa.Text(),
            nullable=False,
            comment="Raw natural-language question submitted by the caller.",
        ),
        sa.Column(
            "structured_response",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Structured data payload returned by the query engine (shape varies by question).",
        ),
        sa.Column(
            "natural_language_response",
            sa.Text(),
            nullable=True,
            comment="Plain-language summary answer produced by the LLM.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of query log creation.",
        ),
    )

    op.create_index(
        "ix_query_logs_dataset_id",
        "query_logs",
        ["dataset_id"],
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Drop all indexes, tables, and enum types in reverse dependency order."""

    # Drop tables in reverse foreign-key dependency order so that
    # referential integrity constraints are never violated during teardown.
    op.drop_index("ix_query_logs_dataset_id", table_name="query_logs")
    op.drop_table("query_logs")

    op.drop_index("ix_findings_severity", table_name="findings")
    op.drop_index("ix_findings_category", table_name="findings")
    op.drop_index("ix_findings_audit_id", table_name="findings")
    op.drop_table("findings")

    op.drop_index("ix_audits_status", table_name="audits")
    op.drop_index("ix_audits_dataset_id", table_name="audits")
    op.drop_table("audits")

    op.drop_table("datasets")

    # Enum types are dropped after the tables that reference them are gone.
    op.execute("DROP TYPE IF EXISTS finding_severity;")
    op.execute("DROP TYPE IF EXISTS finding_category;")
    op.execute("DROP TYPE IF EXISTS audit_status;")
