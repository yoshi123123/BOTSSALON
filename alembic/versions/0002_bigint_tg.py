"""telegram_id to BIGINT

Revision ID: 0002_bigint_tg
Revises: 0001_initial
Create Date: 2026-07-07

Telegram user IDs exceeded int32 range; widen the column. Safe to run on a
database where the column is already BIGINT (ALTER to same type is a no-op).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_bigint_tg"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "telegram_id", type_=sa.BigInteger())


def downgrade() -> None:
    op.alter_column("users", "telegram_id", type_=sa.Integer())
