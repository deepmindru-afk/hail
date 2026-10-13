import pytest
from hailhq.core import sms_registration_fees as fees


def test_twilio_business_filing_fee_is_brand_plus_campaign_vetting() -> None:
    # 46.00 brand (with vetting) + 15.00 campaign vetting
    assert fees.filing_fee_cents("twilio", "business") == 6100


def test_twilio_person_filing_fee() -> None:
    # 4.50 brand + 15.00 campaign vetting
    assert fees.filing_fee_cents("twilio", "person") == 1950


def test_monthly_fee() -> None:
    assert fees.monthly_fee_cents("twilio", "business") == 1000
    assert fees.monthly_fee_cents("twilio", "person") == 200


def test_unknown_provider_raises() -> None:
    with pytest.raises(KeyError):
        fees.filing_fee_cents("didww", "person")


def test_providers_lists_carriers() -> None:
    assert {"twilio", "telnyx"} <= set(fees.providers())
