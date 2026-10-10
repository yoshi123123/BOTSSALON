"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00

Explicit table creation (no metadata.create_all) so the migration runs reliably
through Alembic's transactional DDL without depending on async-engine internals.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

role_enum = sa.Enum("owner", "admin", "master", "client", name="role")
status_enum = sa.Enum(
    "pending",
    "confirmed",
    "completed",
    "cancelled_by_client",
    "cancelled_by_master",
    "cancelled_by_admin",
    "rescheduled",
    "no_show",
    name="appointmentstatus",
)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("telegram_id", sa.BigInteger, nullable=False),
        sa.Column("role", role_enum, nullable=False, server_default="client"),
        sa.Column("full_name", sa.String(255)),
        sa.Column("phone", sa.String(32)),
        sa.Column("username", sa.String(64)),
        sa.Column("language", sa.String(4), nullable=False, server_default="ru"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "masters",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("specialization", sa.String(255)),
        sa.Column("experience_years", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rating", sa.Numeric(3, 1), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("telegram_notifications_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sms_notifications_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("sms_phone", sa.String(32)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("user_id", name="uq_masters_user_id"),
    )

    op.create_table(
        "service_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("service_categories.id")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("default_price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("default_duration_minutes", sa.Integer, nullable=False, server_default="60"),
        sa.Column("buffer_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("photo_file_id", sa.String(255)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "master_services",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("custom_price", sa.Numeric(10, 2)),
        sa.Column("custom_duration_minutes", sa.Integer),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("master_id", "service_id", name="uq_master_service"),
    )

    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False),
        sa.Column("weekday", sa.Integer, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("break_start", sa.Time),
        sa.Column("break_end", sa.Time),
        sa.Column("is_working_day", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("master_id", "weekday", name="uq_master_weekday"),
    )

    op.create_table(
        "schedule_exceptions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("start_time", sa.Time),
        sa.Column("end_time", sa.Time),
        sa.Column("exception_type", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(255)),
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False),
        sa.Column("service_id", sa.Integer, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("status", status_enum, nullable=False, server_default="pending"),
        sa.Column("client_comment", sa.Text),
        sa.Column("cancellation_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_appt_master_time", "appointments", ["master_id", "start_at", "end_at"])
    op.create_index("ix_appt_client", "appointments", ["client_id"])
    op.create_index(
        "uq_active_master_start",
        "appointments",
        ["master_id", "start_at"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending','confirmed')"),
    )

    op.create_table(
        "appointment_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("changed_by_user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("old_data", sa.Text),
        sa.Column("new_data", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "portfolio_items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False),
        sa.Column("telegram_file_id", sa.String(255), nullable=False),
        sa.Column("caption", sa.String(500)),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("client_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("master_id", sa.Integer, sa.ForeignKey("masters.id"), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("text", sa.Text),
        sa.Column("is_visible", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("appointment_id", name="uq_review_appointment"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_rating_range"),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("appointment_id", sa.Integer, sa.ForeignKey("appointments.id")),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("notification_type", sa.String(32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text),
    )

    op.create_table(
        "salon_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, server_default="Мой салон"),
        sa.Column("address", sa.String(500)),
        sa.Column("phone", sa.String(32)),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Chisinau"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="MDL"),
        sa.Column("map_url", sa.String(500)),
        sa.Column("cancellation_policy", sa.Text),
        sa.Column("greeting_text", sa.Text),
        sa.Column("sms_enabled", sa.Boolean, nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_table("salon_settings")
    op.drop_table("notifications")
    op.drop_table("reviews")
    op.drop_table("portfolio_items")
    op.drop_table("appointment_history")
    op.drop_index("uq_active_master_start", table_name="appointments")
    op.drop_index("ix_appt_client", table_name="appointments")
    op.drop_index("ix_appt_master_time", table_name="appointments")
    op.drop_table("appointments")
    op.drop_table("schedule_exceptions")
    op.drop_table("schedules")
    op.drop_table("master_services")
    op.drop_table("services")
    op.drop_table("service_categories")
    op.drop_table("masters")
    op.drop_index("ix_users_telegram_id", table_name="users")
    op.drop_table("users")
    status_enum.drop(op.get_bind(), checkfirst=True)
    role_enum.drop(op.get_bind(), checkfirst=True)
