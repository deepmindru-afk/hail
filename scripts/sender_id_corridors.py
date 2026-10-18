#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["phonenumbers>=9"]
# ///
"""Regenerate ``_REGION_OUTCOMES`` in core/hailhq/core/sender_id.py.

Reads Twilio's per-country SMS guidelines
(https://www.twilio.com/en-us/guidelines/<cc>/sms), "Alphanumeric" table,
and prints one line per region to paste into ``_REGION_OUTCOMES``::

    uv run scripts/sender_id_corridors.py > /tmp/outcomes.txt

Rule, per region, from the "Twilio supported" row of that table:

- "Dynamic" is "Supported" and "Sender ID preserved" is "Yes" (or not
  stated) -> ``custom_ok``: a dynamic alphanumeric sender ID reaches the
  handset as sent, so the org's sender ID (or ``HAIL``) is used.
- "Dynamic" is "Supported" but "Sender ID preserved" is "No" ->
  ``excluded``: operators replace the ID with a random code, so the brand
  would not show; Hail requires a dedicated number instead.
- "Dynamic" is "Not Supported", or only some networks accept it ->
  ``always_number``.
- No guidelines page or no "Alphanumeric" table -> the region is left out
  and falls back to ``always_number`` in ``_classify``.

Australia stays ``platform_default_only`` by hand: the ACMA register
requires pre-registration and Hail registered ``HAIL`` there.
"""

from __future__ import annotations

import html
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import phonenumbers

GUIDELINES = "https://www.twilio.com/en-us/guidelines/{cc}/sms"
HAND_SET = {"AU": "platform_default_only"}
NOTES = {
    "excluded": "Twilio rewrites dynamic sender IDs",
    "always_number": "no dynamic sender ID on Twilio",
}


def _text(fragment: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html.unescape(fragment))
    return re.sub(r"\s+", " ", plain).strip()


def _strip(value: str) -> str:
    return re.sub(r"\s*Learn more.*$", "", value).strip()


def fetch(cc: str) -> str | None:
    req = urllib.request.Request(
        GUIDELINES.format(cc=cc.lower()), headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def alphanumeric_table(page: str) -> tuple[str, dict[str, str]] | None:
    """(country name, {row label: Dynamic-column value}) or None."""
    plain = _text(page)
    name = re.search(r"Locale name ([A-Za-z' ,().&-]+?) ISO code", plain)
    start = page.find('id="guideline-tables"')
    tables = re.finditer(
        r"<h3[^>]*>(.*?)</h3>\s*</div>\s*<div class=\"pricing-table[^>]*>"
        r"\s*<table>(.*?)</table>",
        page[start:] if start >= 0 else page,
        re.DOTALL,
    )
    for table in tables:
        if not _text(table.group(1)).lower().startswith("alphanumeric"):
            continue
        rows = re.findall(r"<tr>(.*?)</tr>", table.group(2), re.DOTALL)
        head = [_text(c) for c in re.findall(r"<th>(.*?)</th>", rows[0], re.DOTALL)]
        if "Dynamic" not in head:
            return None
        dynamic = head.index("Dynamic") - 1
        values: dict[str, str] = {}
        for row in rows[1:]:
            cells = [_text(c) for c in re.findall(r"<td>(.*?)</td>", row, re.DOTALL)]
            if len(cells) > dynamic + 1:
                label = " ".join(cells[0].split()[:2]).lower()
                values[label] = _strip(cells[dynamic + 1])
        return (name.group(1).strip() if name else ""), values
    return None


def classify(values: dict[str, str]) -> tuple[str, str]:
    """(outcome, note)."""
    dynamic = values.get("twilio supported", "").lower()
    preserved = (
        values.get("sender id", "") or values.get("senderid preserved", "")
    ).lower()
    if dynamic in ("supported", "suppported"):
        if preserved.startswith("no"):
            return "excluded", NOTES["excluded"]
        if preserved.startswith("yes"):
            return "custom_ok", ""
        return "custom_ok", "Twilio does not state whether the ID is preserved"
    if dynamic.startswith("supported"):
        return "always_number", "only some networks accept a dynamic sender ID"
    return "always_number", NOTES["always_number"]


def main() -> int:
    regions = sorted(phonenumbers.SUPPORTED_REGIONS)
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = dict(zip(regions, pool.map(fetch, regions)))
    lines: list[str] = []
    skipped: list[str] = []
    for cc in regions:
        page = pages[cc]
        parsed = alphanumeric_table(page) if page else None
        if parsed is None:
            skipped.append(cc)
            continue
        name, values = parsed
        outcome, note = classify(values)
        if cc in HAND_SET:
            outcome = HAND_SET[cc]
            note = "ACMA register requires pre-registration; Hail registered HAIL"
        comment = f"  # {name or cc}" + (f" — {note}" if note else "")
        lines.append(f'    "{cc}": "{outcome}",{comment}')
    print("\n".join(lines))
    print(
        f"# {len(lines)} regions; no Twilio data (fall back to always_number): "
        + " ".join(skipped),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
