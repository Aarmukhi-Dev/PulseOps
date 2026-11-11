"""Add service check history and cached availability state.

Revision ID: 0003_service_availability
Revises: 0002_application_schema
Create Date: 2026-11-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_service_availability"
down_revision: Union[str, Sequence[str], None] = "0002_application_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "monitored_services",
        sa.Column("current_status", sa.String(length=16), server_default=sa.text("'unknown'"), nullable=False),
    )
    op.add_column("monitored_services", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("monitored_services", sa.Column("last_response_time_ms", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_monitored_services_current_status",
        "monitored_services",
        "current_status IN ('unknown', 'healthy', 'unhealthy')",
    )
    op.create_check_constraint(
        "ck_monitored_services_last_response_time_nonnegative",
        "monitored_services",
        "last_response_time_ms IS NULL OR last_response_time_ms >= 0",
    )

    op.create_table(
        "service_checks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_type", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_service_checks_response_time_nonnegative",
        ),
        sa.CheckConstraint("status_code IS NULL OR status_code BETWEEN 100 AND 599", name="ck_service_checks_status_code"),
        sa.CheckConstraint(
            "error_type IS NULL OR error_type IN ('timeout', 'connection_error', 'tls_error', 'http_status', 'invalid_target', 'unsupported_check_type')",
            name="ck_service_checks_error_type",
        ),
        sa.CheckConstraint("is_available = false OR error_type IS NULL", name="ck_service_checks_available_without_error"),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["monitored_services.id"],
            name="fk_service_checks_service_id_monitored_services",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_checks_service_checked_at", "service_checks", ["service_id", "checked_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_service_checks_service_checked_at", table_name="service_checks")
    op.drop_table("service_checks")
    op.drop_constraint("ck_monitored_services_last_response_time_nonnegative", "monitored_services", type_="check")
    op.drop_constraint("ck_monitored_services_current_status", "monitored_services", type_="check")
    op.drop_column("monitored_services", "last_response_time_ms")
    op.drop_column("monitored_services", "last_checked_at")
    op.drop_column("monitored_services", "current_status")
