"""Tests for Sender ID corridor classification and resolution."""

from __future__ import annotations

from hailhq.core.sender_id import resolve_sender
from hailhq.core.sender_id_corridors import CORRIDORS


def test_us_always_requires_dedicated_number() -> None:
    result = resolve_sender("+14155551234", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_canada_always_requires_dedicated_number() -> None:
    # Canadian NANP number (+1 area code 416 = Toronto)
    result = resolve_sender("+14165551234", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_jamaica_shares_plus_one_but_uses_custom_sender_id() -> None:
    # Same +1 calling code as the US; Twilio delivers dynamic sender IDs there.
    result = resolve_sender("+18765551234", custom_sender_id="ACME")
    assert result.kind == "alphanumeric"
    assert result.sender_id == "ACME"


def test_germany_uses_custom_sender_id_when_set() -> None:
    result = resolve_sender("+491701234567", custom_sender_id="ACME")
    assert result.kind == "alphanumeric"
    assert result.sender_id == "ACME"


def test_germany_falls_back_to_platform_default_when_unset() -> None:
    result = resolve_sender("+491701234567", custom_sender_id=None)
    assert result.kind == "alphanumeric"
    assert result.sender_id == "HAIL"


def test_uk_uses_custom_sender_id() -> None:
    result = resolve_sender("+447911123456", custom_sender_id="ACME")
    assert result.kind == "alphanumeric"
    assert result.sender_id == "ACME"


def test_denmark_uses_custom_sender_id() -> None:
    result = resolve_sender("+4552123456", custom_sender_id="ACME")
    assert result.kind == "alphanumeric"
    assert result.sender_id == "ACME"


def test_sweden_uses_custom_sender_id() -> None:
    result = resolve_sender("+46701234567", custom_sender_id="ACME")
    assert result.kind == "alphanumeric"
    assert result.sender_id == "ACME"


def test_australia_ignores_custom_id_uses_platform_default() -> None:
    # Registration-required corridor: custom per-org IDs not supported yet.
    result = resolve_sender("+61412345678", custom_sender_id="ACME")
    assert result.kind == "alphanumeric"
    assert result.sender_id == "HAIL"


def test_india_excluded_requires_dedicated_number() -> None:
    result = resolve_sender("+919876543210", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_finland_rewrites_sender_ids_so_requires_dedicated_number() -> None:
    # Twilio: dynamic sender ID supported, but operators replace it.
    result = resolve_sender("+358401234567", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_czech_partial_network_support_requires_dedicated_number() -> None:
    # Twilio: not supported on T-Mobile and O2 — treated as not supported.
    result = resolve_sender("+420601234567", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_region_without_twilio_data_requires_dedicated_number() -> None:
    # +850 North Korea has no Twilio guidelines page — safe fallback.
    assert "KP" not in CORRIDORS["twilio"]
    result = resolve_sender("+8501912345678", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_unparseable_number_requires_dedicated_number() -> None:
    result = resolve_sender("+999", custom_sender_id="ACME")
    assert result.kind == "dedicated_number_required"


def test_every_region_outcome_is_a_known_value() -> None:
    allowed = {"always_number", "custom_ok", "platform_default_only", "excluded"}
    for carrier in ("twilio", "telnyx"):
        assert set(CORRIDORS[carrier].values()) <= allowed
        assert len(CORRIDORS[carrier]) >= 200


def test_telnyx_has_its_own_rules() -> None:
    # Finland: Twilio replaces a dynamic sender ID, Telnyx keeps it.
    assert resolve_sender("+358401234567", "ACME").kind == "dedicated_number_required"
    telnyx = resolve_sender("+358401234567", "ACME", carrier="telnyx")
    assert telnyx.kind == "alphanumeric"
    assert telnyx.sender_id == "ACME"
    # Australia: HAIL is registered on Twilio only.
    assert resolve_sender("+61412345678", "ACME", carrier="telnyx").kind == (
        "dedicated_number_required"
    )


def test_telnyx_never_sends_a_sender_id_to_north_america() -> None:
    for number in ("+14155551234", "+14165551234", "+17875551234"):
        result = resolve_sender(number, "ACME", carrier="telnyx")
        assert result.kind == "dedicated_number_required"


def test_unknown_carrier_requires_dedicated_number() -> None:
    result = resolve_sender("+4552123456", "ACME", carrier="didww")
    assert result.kind == "dedicated_number_required"
