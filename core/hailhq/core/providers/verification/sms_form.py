"""The form and fixed campaign text for US A2P 10DLC registration. Both
carrier plug-ins use it, so the customer sees one form whatever the carrier.
Carrier words stay out of labels and help."""

from __future__ import annotations

from dataclasses import dataclass

from hailhq.core.providers.verification.base import (
    FieldOption,
    FieldSpec,
    Requirements,
    SubjectType,
)

_BUSINESS_TYPES = (
    FieldOption(key="PRIVATE_PROFIT", label="Private company"),
    FieldOption(key="PUBLIC_PROFIT", label="Publicly traded company"),
    FieldOption(key="NON_PROFIT", label="Non-profit"),
    FieldOption(key="GOVERNMENT", label="Government"),
)
_VERTICALS = (
    ("PROFESSIONAL", "Professional services"),
    ("REAL_ESTATE", "Real estate"),
    ("HEALTHCARE", "Healthcare"),
    ("HUMAN_RESOURCES", "Human resources"),
    ("ENERGY", "Energy"),
    ("ENTERTAINMENT", "Entertainment"),
    ("RETAIL", "Retail"),
    ("TRANSPORTATION", "Transportation"),
    ("AGRICULTURE", "Agriculture"),
    ("INSURANCE", "Insurance"),
    ("POSTAL", "Postal"),
    ("EDUCATION", "Education"),
    ("HOSPITALITY", "Hospitality"),
    ("FINANCIAL", "Financial"),
    ("POLITICAL", "Political"),
    ("GAMBLING", "Gambling"),
    ("LEGAL", "Legal"),
    ("CONSTRUCTION", "Construction"),
    ("NGO", "Non-governmental organization"),
    ("MANUFACTURING", "Manufacturing"),
    ("GOVERNMENT", "Government"),
    ("TECHNOLOGY", "Technology"),
    ("COMMUNICATION", "Communication"),
)
_YES_NO = (FieldOption(key="YES", label="Yes"), FieldOption(key="NO", label="No"))

_BUSINESS_FIELDS = (
    FieldSpec(name="legal_name", label="Legal company name"),
    FieldSpec(name="business_type", label="Company type", options=_BUSINESS_TYPES),
    FieldSpec(
        name="ein",
        label="US employer ID (EIN)",
        pattern=r"^\d{2}-?\d{7}$",
        help="Nine digits, as on your IRS letter.",
    ),
    FieldSpec(
        name="industry",
        label="Industry",
        options=tuple(FieldOption(key=k, label=v) for k, v in _VERTICALS),
    ),
    FieldSpec(
        name="website",
        label="Website",
        kind="url",
        help="The carrier checks that the site names your company.",
    ),
    FieldSpec(name="rep_name", label="Contact person name"),
    FieldSpec(name="rep_email", label="Contact person email", kind="email"),
    FieldSpec(name="rep_phone", label="Contact person phone", kind="phone"),
    FieldSpec(name="rep_title", label="Contact person job title"),
)
_PERSON_FIELDS = (
    FieldSpec(name="first_name", label="First name"),
    FieldSpec(name="last_name", label="Last name"),
    FieldSpec(name="email", label="Email", kind="email"),
    FieldSpec(
        name="mobile_phone_number",
        label="Your mobile number",
        kind="phone",
        help=(
            "The carrier texts this number. Reply YES to confirm. Use your own "
            "mobile, not a Hail number. A mobile can confirm three registrations "
            "in its lifetime."
        ),
    ),
)
_CAMPAIGN_FIELDS = (
    FieldSpec(
        name="campaign_description",
        label="What you send",
        help="One or two sentences. Example: appointment reminders and replies to customer questions.",
    ),
    FieldSpec(name="sample_1", label="Sample message 1"),
    FieldSpec(name="sample_2", label="Sample message 2"),
    FieldSpec(
        name="opt_in_description",
        label="How people agree to receive texts",
        help="Example: they enter their number on our website and tick a box.",
    ),
    FieldSpec(name="has_links", label="Do your texts contain links?", options=_YES_NO),
)


def sms_requirements(provider: str, subject_type: SubjectType) -> Requirements:
    subject = _PERSON_FIELDS if subject_type == "person" else _BUSINESS_FIELDS
    return Requirements(
        provider=provider,
        country_code="US",
        number_type="local",
        subject_type=subject_type,
        required=True,
        fields=subject + _CAMPAIGN_FIELDS,
        documents=(),
        address_required=True,
        subject_types=("person", "business"),
    )


@dataclass(frozen=True)
class CampaignText:
    use_case: str
    description: str
    message_flow: str
    samples: list[str]
    has_links: bool


_OPT_OUT = " Reply STOP to opt out, HELP for help."


def _at_least(text: str, n: int, pad: str) -> str:
    text = text.strip()
    return text if len(text) >= n else (text + " " + pad).strip()


def campaign_text(fields: dict[str, str], subject_type: SubjectType) -> CampaignText:
    """Carrier minimums: description 40+, message flow 40+, samples 20+."""
    description = _at_least(
        fields["campaign_description"],
        40,
        "Messages are sent only to people who agreed to receive them.",
    )
    flow = _at_least(
        "Recipients opt in as follows: " + fields["opt_in_description"],
        40,
        "They can reply STOP at any time to opt out.",
    )
    samples = [
        _at_least(fields["sample_1"], 20, _OPT_OUT),
        _at_least(fields["sample_2"], 20, _OPT_OUT),
    ]
    return CampaignText(
        use_case="SOLE_PROPRIETOR" if subject_type == "person" else "MIXED",
        description=description,
        message_flow=flow,
        samples=samples,
        has_links=fields["has_links"].upper() == "YES",
    )
