"""Add reminder timestamps to number_dunning.

hail-website's dunning job emails owners again 3 days and 1 day before
release. Each column is set once its reminder reached at least one owner,
so a reminder is sent once per dunning episode. Deleting the row (top-up
or release) resets both.

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "number_dunning",
        sa.Column("reminder_3d_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "number_dunning",
        sa.Column("reminder_1d_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("number_dunning", "reminder_1d_sent_at")
    op.drop_column("number_dunning", "reminder_3d_sent_at")
