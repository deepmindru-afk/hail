"""Carrier fees for US A2P 10DLC registration, read from
``costs/sms-registration.json`` and passed through to the customer at cost."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from hailhq.core import telephony_catalog

_FILE = "sms-registration.json"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict]:
    directory = Path(
        os.environ.get(
            "HAIL_TELEPHONY_CATALOG_DIR", str(telephony_catalog._DEFAULT_DIR)
        )
    )
    data = json.loads((directory / _FILE).read_text())
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
