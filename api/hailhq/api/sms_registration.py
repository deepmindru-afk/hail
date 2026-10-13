"""Put an organization's US long codes on its approved SMS registration."""

from __future__ import annotations

import logging
from uuid import UUID

from hailhq.core.models import CarrierVerification, PhoneNumber
from hailhq.core.providers.verification.base import SmsRegistrationProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def registered_numbers(
    db: AsyncSession, row: CarrierVerification
) -> list[PhoneNumber]:
    """The org's active US long codes on the row's carrier that belong on the
    registration, oldest first. A person's registration takes one number."""
    numbers = (
        (
            await db.execute(
                select(PhoneNumber)
                .where(
                    PhoneNumber.organization_id == row.organization_id,
                    PhoneNumber.provider == row.provider,
                    PhoneNumber.provisioning_state == "active",
                    PhoneNumber.country_code == "US",
                    PhoneNumber.number_type == "local",
                    PhoneNumber.capabilities.any("sms"),
                    PhoneNumber.provider_resource_id.is_not(None),
                )
                .order_by(PhoneNumber.acquired_at.nulls_last(), PhoneNumber.id)
            )
        )
        .scalars()
        .all()
    )
    if row.subject_type == "person":
        return list(numbers[:1])
    return list(numbers)


async def attach_org_numbers(
    db: AsyncSession, row: CarrierVerification, provider: SmsRegistrationProvider
) -> bool:
    """Attach every active US long code of the organization on this carrier.
    Stops at the first failure and returns False; the next pass tries again
    (attach is idempotent at the carrier)."""
    for number in await registered_numbers(db, row):
        try:
            await provider.attach_number(
                row.provider_refs,
                provider_resource_id=number.provider_resource_id,
                e164=number.e164,
            )
        except Exception:
            logger.warning(
                "SMS registration attach failed for number %s",
                number.id,
                exc_info=True,
            )
            return False
    return True


async def approved_registration(
    db: AsyncSession, organization_id: UUID, provider: str
) -> CarrierVerification | None:
    return (
        await db.execute(
            select(CarrierVerification).where(
                CarrierVerification.organization_id == organization_id,
                CarrierVerification.provider == provider,
                CarrierVerification.purpose == "sms",
                CarrierVerification.state == "approved",
            )
        )
    ).scalar_one_or_none()


async def attach_if_registered(db: AsyncSession, number: PhoneNumber, registry) -> None:
    """A newly active US long code joins the org's approved registration, when
    there is one. Failures are logged; the number still works for voice."""
    if number.country_code != "US" or number.number_type != "local":
        return
    if number.provider_resource_id is None or number.organization_id is None:
        return
    row = await approved_registration(db, number.organization_id, number.provider)
    if row is None:
        return
    provider = registry(number.provider, "sms")
    if not isinstance(provider, SmsRegistrationProvider):
        return
    if number.id not in {n.id for n in await registered_numbers(db, row)}:
        return  # a person's registration holds its first number only
    try:
        await provider.attach_number(
            row.provider_refs,
            provider_resource_id=number.provider_resource_id,
            e164=number.e164,
        )
    except Exception:
        logger.warning(
            "SMS registration attach failed for number %s", number.id, exc_info=True
        )
