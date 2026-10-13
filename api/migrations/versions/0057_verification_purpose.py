"""Add ``purpose`` to carrier_verifications: 'number' (regulatory bundle
for buying a number) or 'sms' (US A2P 10DLC brand + campaign). The live
uniqueness index includes it so an org can hold one of each per carrier
and country.

Revision ID: 0057
Revises: 0056
"""

from __future__ import annotations

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE carrier_verifications ADD COLUMN purpose TEXT NOT NULL "
        "DEFAULT 'number'"
    )
    op.execute(
        "ALTER TABLE carrier_verifications ADD CONSTRAINT "
        "carrier_verifications_purpose_check CHECK (purpose IN ('number','sms'))"
    )
    op.execute("DROP INDEX IF EXISTS carrier_verifications_live_uniq")
    op.execute(
        "CREATE UNIQUE INDEX carrier_verifications_live_uniq ON "
        "carrier_verifications (organization_id, provider, country_code, "
        "number_type, purpose) WHERE state NOT IN ('cancelled','rejected')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS carrier_verifications_live_uniq")
    op.execute(
        "CREATE UNIQUE INDEX carrier_verifications_live_uniq ON "
        "carrier_verifications (organization_id, provider, country_code, "
        "number_type) WHERE state NOT IN ('cancelled','rejected')"
    )
    op.execute(
        "ALTER TABLE carrier_verifications DROP CONSTRAINT "
        "carrier_verifications_purpose_check"
    )
    op.execute("ALTER TABLE carrier_verifications DROP COLUMN purpose")
