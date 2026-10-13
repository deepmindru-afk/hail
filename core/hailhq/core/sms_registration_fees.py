"""Carrier fees for US A2P 10DLC registration, read from
``costs/sms-registration.json`` and passed through to the customer at cost."""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache

from hailhq.core import telephony_catalog

_FILE = "sms-registration"
# Monthly campaign fees a carrier bills at least, counted from approval.
# Telnyx bills campaign fees for three months initially
# (https://support.telnyx.com/en/articles/5634625-10dlc-fees-and-charges);
# a carrier not listed bills month by month. The website's monthly rater
# (hail-website lib/monthly-fee-rater.ts) applies the same minimum.
_MINIMUM_MONTHS = {"telnyx": 3}


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    data = json.loads(telephony_catalog._path(_FILE).read_text())
    return {row["provider"]: row for row in data["providers"]}


def _cents(value: str) -> int:
    return int((Decimal(value) * 100).to_integral_value())


def providers() -> list[str]:
    """Carriers that have an SMS registration fee."""
    return list(_load())


def filing_fee_cents(provider: str, subject_type: str) -> int:
    """One-time fee charged when the registration is filed: brand plus
    campaign vetting. Raises KeyError for a carrier with no SMS registration."""
    row = _load()[provider][subject_type]
    return _cents(row["brand_usd"]) + _cents(row["campaign_vetting_usd"])


def monthly_fee_cents(provider: str, subject_type: str) -> int:
    row = _load()[provider][subject_type]
    return _cents(row["campaign_monthly_usd"])


def minimum_months(provider: str) -> int:
    """Monthly fees charged at least, from approval, even when the
    registration is cancelled sooner."""
    return _MINIMUM_MONTHS.get(provider, 1)
