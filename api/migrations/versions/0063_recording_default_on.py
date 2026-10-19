"""Recording on by default. A workspace with no saved choice records with the
service default retention; rows that exist already count as confirmed, so
only a new workspace is asked once during onboarding."""

from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE organization_call_settings "
        "ADD COLUMN recording_confirmed_at TIMESTAMPTZ"
    )
    op.execute(
        "UPDATE organization_call_settings SET recording_confirmed_at = now() "
        "WHERE recording_enabled IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE organization_call_settings DROP COLUMN recording_confirmed_at"
    )
