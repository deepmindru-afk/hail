"""Whether a text may leave a US long code for a US number: only when that
number is on an approved US SMS registration of its organization."""

from __future__ import annotations

from uuid import UUID

import phonenumbers
from hailhq.core.models import CarrierVerification, PhoneNumber
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BLOCK_MESSAGE = (
    "US texting from this number needs SMS registration. Open Numbers in the "
    "console and choose Register for US texting."
)


def is_us(e164: str) -> bool:
    """A +1 number outside the US (Canada, the Caribbean) is not US. An
    unknown +1 area code counts as US, so the gate errs toward blocking."""
    if not e164.startswith("+1"):
        return False
    try:
        region = phonenumbers.region_code_for_number(phonenumbers.parse(e164))
    except phonenumbers.NumberParseException:
        return True
    return region in (None, "US")


def _approved_registration_ids():
    return select(CarrierVerification.id).where(
        CarrierVerification.purpose == "sms",
        CarrierVerification.state == "approved",
    )


async def us_registration_block(
    db: AsyncSession, organization_id: UUID, from_number: PhoneNumber, to_e164: str
) -> str | None:
    if from_number.country_code != "US" or not is_us(to_e164):
        return None  # a Canadian long code, or a text to outside the US
    if from_number.number_type == "toll_free":
        return None
    if from_number.sms_registration_id is None:
        return BLOCK_MESSAGE
    approved = (
        await db.execute(
            _approved_registration_ids().where(
                CarrierVerification.id == from_number.sms_registration_id,
                CarrierVerification.organization_id == organization_id,
            )
        )
    ).scalar_one_or_none()
    return None if approved else BLOCK_MESSAGE


async def registered_sms_number(
    db: AsyncSession, organization_id: UUID
) -> PhoneNumber | None:
    """The org's oldest active number that can text and is on an approved
    US SMS registration. POST /sms without ``from`` prefers it for a US
    destination."""
    return (
        await db.execute(
            select(PhoneNumber)
            .where(
                PhoneNumber.organization_id == organization_id,
                PhoneNumber.provisioning_state == "active",
                PhoneNumber.capabilities.any("sms"),
                PhoneNumber.sms_registration_id.in_(
                    _approved_registration_ids().where(
                        CarrierVerification.organization_id == organization_id
                    )
                ),
            )
            .order_by(PhoneNumber.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()
