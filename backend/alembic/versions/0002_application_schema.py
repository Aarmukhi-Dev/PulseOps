"""Create the initial PulseOps application schema.

Revision ID: 0002_application_schema
Revises: 0001_initial
Create Date: 2026-11-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_application_schema"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email = lower(btrim(email))", name="ck_users_email_normalized"),
        sa.CheckConstraint("length(password_hash) > 0", name="ck_users_password_hash_nonempty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "monitored_services",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("check_type", sa.String(length=16), server_default=sa.text("'http'"), nullable=False),
        sa.Column("target", sa.String(length=2048), nullable=False),
        sa.Column("check_interval_seconds", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column("expected_status_code", sa.Integer(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("check_type IN ('http', 'tcp')", name="ck_monitored_services_check_type"),
        sa.CheckConstraint("check_interval_seconds > 0", name="ck_monitored_services_interval_positive"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_monitored_services_timeout_positive"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_monitored_services_created_by_users", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_monitored_services_is_enabled", "monitored_services", ["is_enabled"])
    op.create_index("ix_monitored_services_created_by", "monitored_services", ["created_by"])

    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=16), server_default=sa.text("'medium'"), nullable=False),
        sa.Column("status", sa.String(length=24), server_default=sa.text("'open'"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="ck_incidents_severity"),
        sa.CheckConstraint("status IN ('open', 'acknowledged', 'resolved')", name="ck_incidents_status"),
        sa.ForeignKeyConstraint(["service_id"], ["monitored_services.id"], name="fk_incidents_service_id_monitored_services", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_service_status_started", "incidents", ["service_id", "status", "started_at"])
    op.create_index("ix_incidents_status_severity_started", "incidents", ["status", "severity", "started_at"])
    op.create_index(
        "uq_incidents_one_active_per_service",
        "incidents",
        ["service_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'acknowledged')"),
    )

    op.create_table(
        "incident_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'acknowledged', 'status_changed', 'severity_changed', 'commented', 'resolved', 'reopened')",
            name="ck_incident_events_event_type",
        ),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], name="fk_incident_events_incident_id_incidents", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_incident_events_actor_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incident_events_incident_created_id", "incident_events", ["incident_id", "created_at", "id"])
    op.create_index("ix_incident_events_actor_user_id", "incident_events", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_incident_events_actor_user_id", table_name="incident_events")
    op.drop_index("ix_incident_events_incident_created_id", table_name="incident_events")
    op.drop_table("incident_events")
    op.drop_index("uq_incidents_one_active_per_service", table_name="incidents")
    op.drop_index("ix_incidents_status_severity_started", table_name="incidents")
    op.drop_index("ix_incidents_service_status_started", table_name="incidents")
    op.drop_table("incidents")
    op.drop_index("ix_monitored_services_created_by", table_name="monitored_services")
    op.drop_index("ix_monitored_services_is_enabled", table_name="monitored_services")
    op.drop_table("monitored_services")
    op.drop_table("users")
