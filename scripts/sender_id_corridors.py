#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["phonenumbers>=9"]
# ///
"""Regenerate core/hailhq/core/sender_id_corridors.py from the carriers'
own per-country sender ID documentation::

    uv run scripts/sender_id_corridors.py

One table per carrier that can send sender-ID SMS (``sender_id_sms_carrier``
in core/hailhq/core/config.py), keyed by ISO 3166-1 alpha-2 region:

- ``twilio``: https://www.twilio.com/en-us/guidelines/<cc>/sms, the
  "Alphanumeric" table, "Twilio supported" row. "Dynamic" supported and
  "Sender ID preserved" yes (or not stated) -> ``custom_ok``; dynamic
  supported but the ID is replaced -> ``excluded``; not supported, or only
  on some networks -> ``always_number``. A region without a guidelines
  page is left out.
- ``telnyx``: https://support.telnyx.com/en/articles/6354449, the
  "Alphanumeric Sender ID maintained?" column. "Yes" -> ``custom_ok``;
  "No" (the ID is changed to ensure delivery) -> ``excluded``; anything
  needing registration, only some networks, local brands only, or "N/A"
  -> ``always_number``.

Australia is ``platform_default_only`` on Twilio by hand: the ACMA register
requires pre-registration and Hail registered ``HAIL`` there.
"""

from __future__ import annotations

import datetime as dt
import html
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import phonenumbers

TWILIO_GUIDELINES = "https://www.twilio.com/en-us/guidelines/{cc}/sms"
TELNYX_ARTICLE = (
    "https://support.telnyx.com/en/articles/"
    "6354449-global-messaging-alphanumeric-sender-id-capabilities"
)
OUTPUT = Path(__file__).resolve().parents[1] / "core/hailhq/core/sender_id_corridors.py"
HAND_SET = {
    "twilio": {
        "AU": (
            "platform_default_only",
            "ACMA register requires pre-registration; Hail registered HAIL",
        )
    }
}


def _text(fragment: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html.unescape(fragment))
    return re.sub(r"\s+", " ", plain).strip()


def _get(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


# --- Twilio -----------------------------------------------------------------


def _twilio_alphanumeric_table(page: str) -> tuple[str, dict[str, str]] | None:
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
                values[label] = re.sub(r"\s*Learn more.*$", "", cells[dynamic + 1])
        return (name.group(1).strip() if name else ""), values
    return None


def _twilio_classify(values: dict[str, str]) -> tuple[str, str]:
    dynamic = values.get("twilio supported", "").lower()
    preserved = (
        values.get("sender id", "") or values.get("senderid preserved", "")
    ).lower()
    if dynamic in ("supported", "suppported"):
        if preserved.startswith("no"):
            return "excluded", "Twilio rewrites dynamic sender IDs"
        if preserved.startswith("yes"):
            return "custom_ok", ""
        return "custom_ok", "Twilio does not state whether the ID is preserved"
    if dynamic.startswith("supported"):
        return "always_number", "only some networks accept a dynamic sender ID"
    return "always_number", "no dynamic sender ID on Twilio"


def twilio() -> tuple[dict[str, tuple[str, str, str]], list[str]]:
    regions = sorted(phonenumbers.SUPPORTED_REGIONS)
    with ThreadPoolExecutor(max_workers=8) as pool:
        pages = dict(
            zip(
                regions,
                pool.map(
                    lambda cc: _get(TWILIO_GUIDELINES.format(cc=cc.lower())), regions
                ),
            )
        )
    table: dict[str, tuple[str, str, str]] = {}
    skipped: list[str] = []
    for cc in regions:
        parsed = _twilio_alphanumeric_table(pages[cc]) if pages[cc] else None
        if parsed is None:
            skipped.append(cc)
            continue
        name, values = parsed
        outcome, note = _twilio_classify(values)
        table[cc] = (name or cc, outcome, note)
    return table, skipped


# --- Telnyx -----------------------------------------------------------------


def _telnyx_classify(maintained: str) -> tuple[str, str]:
    value = maintained.strip()
    lower = value.lower()
    if lower == "yes":
        return "custom_ok", ""
    if lower.startswith("no"):
        return "excluded", "Telnyx changes the sender ID to ensure delivery"
    if lower == "n/a":
        return "always_number", "no Telnyx data"
    return "always_number", f"Telnyx: {value}"


def telnyx() -> tuple[dict[str, tuple[str, str, str]], list[str]]:
    page = _get(TELNYX_ARTICLE)
    if page is None:
        raise SystemExit(f"Telnyx article not found: {TELNYX_ARTICLE}")
    html_table = re.search(r"<table.*?</table>", page, re.DOTALL)
    if html_table is None:
        raise SystemExit("Telnyx article has no table")
    table: dict[str, tuple[str, str, str]] = {}
    for row in re.findall(r"<tr.*?</tr>", html_table.group(0), re.DOTALL):
        cells = [_text(c) for c in re.findall(r"<t[dh].*?</t[dh]>", row, re.DOTALL)]
        if len(cells) != 5 or not re.fullmatch(r"[A-Z]{2}", cells[0]):
            continue
        cc, name, _dial, _mcc, maintained = cells
        outcome, note = _telnyx_classify(maintained)
        table[cc] = (name, outcome, note)
    skipped = sorted(set(phonenumbers.SUPPORTED_REGIONS) - set(table))
    return table, skipped


# --- Output -----------------------------------------------------------------


def render(carrier: str, table: dict[str, tuple[str, str, str]]) -> str:
    lines = [f'    "{carrier}": {{']
    for cc in sorted(table):
        name, outcome, note = table[cc]
        if cc in HAND_SET.get(carrier, {}):
            outcome, note = HAND_SET[carrier][cc]
        comment = f"  # {name}" + (f" — {note}" if note else "")
        lines.append(f'        "{cc}": "{outcome}",{comment}')
    lines.append("    },")
    return "\n".join(lines)


def main() -> int:
    carriers = {"twilio": twilio, "telnyx": telnyx}
    bodies: list[str] = []
    for carrier, fetch in carriers.items():
        table, skipped = fetch()
        bodies.append(render(carrier, table))
        print(
            f"{carrier}: {len(table)} regions; left out (fall back to always_number): "
            + " ".join(skipped),
            file=sys.stderr,
        )
    today = dt.date.today().isoformat()
    OUTPUT.write_text(
        '"""Sender ID corridors per carrier. GENERATED by\n'
        "scripts/sender_id_corridors.py — do not edit by hand; rerun the script.\n"
        "\n"
        f"Fetched {today} from the carriers' own per-country documentation (see\n"
        "the script for the sources and the classification rule). Keyed by the\n"
        "carrier named in ``sender_id_sms_carrier`` and then by the ISO 3166-1\n"
        "alpha-2 region of the destination number.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
        "\n"
        "from typing import Literal\n"
        "\n"
        "CorridorOutcome = Literal[\n"
        '    "always_number", "custom_ok", "platform_default_only", "excluded"\n'
        "]\n"
        "\n"
        "CORRIDORS: dict[str, dict[str, CorridorOutcome]] = {\n"
        + "\n".join(bodies)
        + "\n}\n"
    )
    print(f"wrote {OUTPUT}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
