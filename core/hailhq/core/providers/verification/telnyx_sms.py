"""Telnyx plug-in for US A2P 10DLC registration: a brand, optional vetting,
then a campaign; numbers are linked to the campaign one by one.

Sole proprietor (person) registration needs a PIN step Telnyx sends by SMS; not
built in this release."""

from __future__ import annotations

import logging
import re

import httpx
from hailhq.core.providers.telnyx import TelnyxClient
from hailhq.core.providers.verification.base import (
    DraftResult,
    Problem,
    ProviderStatus,
    Requirements,
    SmsRegistrationProvider,
    UnsupportedSubjectType,
    VerificationProviderError,
)
from hailhq.core.providers.verification.sms_form import (
    campaign_text,
    sms_requirements,
)

logger = logging.getLogger(__name__)

_EIN = re.compile(r"^\d{2}-?\d{7}$")
_OPT_OUT = "STOP,STOPALL,UNSUBSCRIBE,CANCEL,END,QUIT"
_HELP = "HELP,INFO"
_VERIFIED = {"VERIFIED", "VETTED_VERIFIED"}
_APPROVED = {"TCR_ACCEPTED", "MNO_ACCEPTED", "ACCEPTED", "ACTIVE"}
_REJECTED = {"TCR_FAILED", "MNO_REJECTED", "REJECTED", "FAILED"}


class TelnyxSmsRegistrationProvider(SmsRegistrationProvider):
    name = "telnyx"

    def __init__(self, api_key=None, client=None) -> None:
        self._api = TelnyxClient(api_key, client)

    async def requirements(
        self, country_code, number_type, subject_type
    ) -> Requirements:
        if subject_type == "person":
            raise UnsupportedSubjectType(
                "This carrier registers companies only for US texting.",
                allowed=("business",),
            )
        return sms_requirements(self.name, subject_type).model_copy(
            update={"subject_types": ("business",)}
        )

    def _validate(self, fields, address, subject_type) -> list[Problem]:
        problems: list[Problem] = []
        if subject_type != "business":
            return [Problem(field="", message="Only companies can register here.")]
        for spec in sms_requirements(self.name, subject_type).fields:
            if spec.required and not (fields.get(spec.name) or "").strip():
                problems.append(Problem(field=spec.name, message="This is required."))
        if fields.get("ein") and not _EIN.match(fields["ein"]):
            problems.append(
                Problem(field="ein", message="Nine digits, like 12-3456789.")
            )
        if address is None:
            problems.append(Problem(field="address", message="An address is required."))
        return problems

    async def create_draft(
        self,
        *,
        organization_id,
        contact_email,
        requirements,
        fields,
        address,
        documents,
        messaging_service_sid=None,
    ) -> DraftResult:
        subject_type = requirements.subject_type
        problems = self._validate(fields, address, subject_type)
        if problems:
            return DraftResult(refs={}, problems=problems)
        text = campaign_text(fields, subject_type)
        refs: dict = {
            "subject_type": subject_type,
            "campaign": text.__dict__,
            "messaging_profile_id": messaging_service_sid,
        }
        try:
            await self._build(refs, fields, address, subject_type)
        except Exception as exc:
            await self.discard(refs)
            if isinstance(exc, httpx.HTTPStatusError):
                code = exc.response.status_code
                logger.warning("10DLC draft failed: status=%s", code)
                if 400 <= code < 500:
                    return DraftResult(
                        refs={},
                        problems=[
                            Problem(field="", message=_safe_message(exc.response))
                        ],
                    )
            raise VerificationProviderError("Telnyx request failed") from exc
        return DraftResult(refs=refs)

    async def _build(self, refs, fields, address, subject_type) -> None:
        display = fields["legal_name"]
        body = {
            "entityType": fields["business_type"],
            "email": fields["rep_email"],
            "phone": fields["rep_phone"],
            "vertical": fields["industry"],
            "ein": fields["ein"].replace("-", ""),
            "website": fields["website"],
        }
        body.update(
            displayName=display,
            companyName=display,
            street=address.street,
            city=address.city,
            state=address.region,
            postalCode=address.postal_code,
            country=address.country_code,
        )
        brand = await self._api.request("POST", "/10dlc/brand", json=body)
        refs["brand_id"] = brand["brandId"]
        await self._api.request(
            "POST",
            f"/10dlc/brand/{refs['brand_id']}/vetting",
            json={"vettingProvider": "AEGIS", "vettingClass": "STANDARD"},
        )

    async def check(self, refs) -> list[Problem]:
        return []

    async def submit(self, refs) -> None:
        # The brand is registered when created; nothing more to send.
        return None

    async def status(self, refs) -> ProviderStatus:
        try:
            brand = await self._api.request("GET", f"/10dlc/brand/{refs['brand_id']}")
            if brand.get("failureReasons"):
                return ProviderStatus(
                    state="rejected", reason=str(brand["failureReasons"])
                )
            if brand.get("identityStatus") not in _VERIFIED:
                return ProviderStatus(state="pending")
            if "campaign_id" not in refs:
                text = refs["campaign"]
                campaign = await self._api.request(
                    "POST",
                    "/10dlc/campaignBuilder",
                    json={
                        "brandId": refs["brand_id"],
                        "usecase": text["use_case"],
                        "description": text["description"],
                        "messageFlow": text["message_flow"],
                        "sample1": text["samples"][0],
                        "sample2": text["samples"][1],
                        "embeddedLink": text["has_links"],
                        "embeddedPhone": False,
                        "numberPool": False,
                        "ageGated": False,
                        "directLending": False,
                        "subscriberOptin": True,
                        "subscriberOptout": True,
                        "subscriberHelp": True,
                        "optoutKeywords": _OPT_OUT,
                        "helpKeywords": _HELP,
                        "helpMessage": "Reply STOP to opt out. For help contact hi@hail.so.",
                        "optinMessage": "You are opted in. Reply STOP to opt out, HELP for help.",
                    },
                )
                refs["campaign_id"] = campaign["campaignId"]
                return ProviderStatus(state="pending")
            campaign = await self._api.request(
                "GET", f"/10dlc/campaign/{refs['campaign_id']}"
            )
        except (httpx.HTTPError, KeyError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                logger.warning(
                    "10DLC status failed: status=%s", exc.response.status_code
                )
            raise VerificationProviderError("Telnyx request failed") from exc
        status = (campaign.get("campaignStatus") or "").upper()
        if status in _APPROVED:
            return ProviderStatus(state="approved")
        if status in _REJECTED:
            return ProviderStatus(
                state="rejected",
                reason=str(
                    campaign.get("failureReasons")
                    or "the carrier rejected the campaign"
                ),
            )
        return ProviderStatus(state="pending")

    async def purchase_handle(self, refs) -> dict:
        return {}

    async def attach_number(self, refs, *, provider_resource_id, e164) -> None:
        try:
            await self._api.request(
                "POST",
                "/10dlc/phone_number_campaigns",
                json={"phoneNumber": e164, "campaignId": refs["campaign_id"]},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:  # already linked
                return
            logger.warning("10DLC attach failed: status=%s", exc.response.status_code)
            raise VerificationProviderError("Telnyx request failed") from exc
        except (httpx.HTTPError, KeyError) as exc:
            raise VerificationProviderError("Telnyx request failed") from exc

    async def discard(self, refs) -> None:
        steps = (
            ("campaign", refs.get("campaign_id")),
            ("brand", refs.get("brand_id")),
        )
        for key, resource_id in steps:
            if not resource_id:
                continue
            try:
                await self._api.request("DELETE", f"/10dlc/{key}/{resource_id}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    logger.warning(
                        "10DLC discard failed: step=%s status=%s",
                        key,
                        exc.response.status_code,
                    )
            except Exception:
                logger.warning("10DLC discard failed: step=%s", key)


def _safe_message(response: httpx.Response) -> str:
    """A short neutral sentence; never the carrier's own text."""
    try:
        errors = response.json().get("errors") or []
        low = " ".join(
            f"{e.get('title', '')} {e.get('detail', '')}" for e in errors
        ).lower()
    except (ValueError, AttributeError, TypeError):
        low = ""
    for words, text in (
        (("ein", "tax id", "registration number"), "Check the tax ID (EIN)."),
        (("website", "url"), "Check the website address."),
        (("address", "street", "postal", "zip"), "Check the address."),
        (("phone", "mobile"), "Check the phone number."),
    ):
        if any(re.search(rf"\b{w}\b", low) for w in words):
            return text
    return "The carrier refused a detail. Check your entries and try again."
