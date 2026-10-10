"""drop redis dependency: language_selected flag + sent_notifications marks

Revision ID: 0003_no_redis
Revises: 0002_bigint_tg
Create Date: 2026-10-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_no_redis"
down_revision: str | None = "0002_bigint_tg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("language_selected", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "sent_notifications",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sent_notifications")
    op.drop_column("users", "language_selected")
