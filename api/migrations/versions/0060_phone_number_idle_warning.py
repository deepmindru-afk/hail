"""Add phone_numbers.idle_warned_at + idle_release_after.

Warn-then-release state for dedicated numbers with no calls or texts for
the idle window. Set and cleared by hail-website's daily billing job
(lib/idle-number-release.ts): both columns are set when owners are warned,
and cleared when the number sees activity again or once it is released.
``idle_release_after`` is fixed at warn time so the announced date never
moves.

Revision ID: 0060
Revises: 0059
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "phone_numbers",
        sa.Column("idle_warned_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "phone_numbers",
        sa.Column("idle_release_after", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("phone_numbers", "idle_release_after")
    op.drop_column("phone_numbers", "idle_warned_at")
