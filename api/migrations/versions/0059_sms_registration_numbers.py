"""Track which numbers are on a US SMS registration, and when a
registration was cancelled.

``phone_numbers.sms_registration_id``: the approved ``purpose='sms'``
carrier_verifications row whose campaign holds this number. The send gate
lets a US-to-US text leave a long code only when this points at an
approved registration.

``carrier_verifications.cancelled_at``: when the row was cancelled. The
monthly fee of an SMS registration is billed through the month of this
date.

Revision ID: 0059
Revises: 0058
"""

from __future__ import annotations

from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE phone_numbers ADD COLUMN sms_registration_id UUID "
        "REFERENCES carrier_verifications(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX phone_numbers_sms_registration_id_idx ON phone_numbers "
        "(sms_registration_id) WHERE sms_registration_id IS NOT NULL"
    )
    op.execute("ALTER TABLE carrier_verifications ADD COLUMN cancelled_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE carrier_verifications DROP COLUMN cancelled_at")
    op.execute("DROP INDEX IF EXISTS phone_numbers_sms_registration_id_idx")
    op.execute("ALTER TABLE phone_numbers DROP COLUMN sms_registration_id")
