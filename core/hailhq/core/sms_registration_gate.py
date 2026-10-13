"""Whether a text may leave a US long code for a US number: only when the
organization holds an approved US SMS registration with that carrier."""

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


def _is_us(e164: str) -> bool:
    """A +1 number outside the US (Canada, the Caribbean) is not US. An
    unknown +1 area code counts as US, so the gate errs toward blocking."""
    if not e164.startswith("+1"):
        return False
    try:
        region = phonenumbers.region_code_for_number(phonenumbers.parse(e164))
    except phonenumbers.NumberParseException:
        return True
    return region in (None, "US")


async def us_registration_block(
    db: AsyncSession, organization_id: UUID, from_number: PhoneNumber, to_e164: str
) -> str | None:
    if from_number.country_code != "US" or not _is_us(to_e164):
        return None  # a Canadian long code, or a text to outside the US
    if from_number.number_type == "toll_free":
        return None
    approved = (
        await db.execute(
            select(CarrierVerification.id)
            .where(
                CarrierVerification.organization_id == organization_id,
                CarrierVerification.provider == from_number.provider,
                CarrierVerification.purpose == "sms",
                CarrierVerification.state == "approved",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return None if approved else BLOCK_MESSAGE
