import json

import httpx
import pytest

from hailhq.core.providers.verification.base import (
    Address,
    UnsupportedSubjectType,
    VerificationProviderError,
)
from hailhq.core.providers.verification.telnyx_sms import (
    TelnyxSmsRegistrationProvider,
)

FIELDS = {
    "legal_name": "Acme Inc",
    "business_type": "PRIVATE_PROFIT",
    "ein": "12-3456789",
    "industry": "RETAIL",
    "website": "https://acme.example",
    "rep_name": "Ada Lovelace",
    "rep_email": "ada@acme.example",
    "rep_phone": "+15125550100",
    "rep_title": "CEO",
    "campaign_description": "Order updates and delivery notices for customers who ordered on our site.",
    "sample_1": "Acme: your order 123 shipped. Reply STOP to opt out.",
    "sample_2": "Acme: your order 123 was delivered. Reply STOP to opt out.",
    "opt_in_description": "Customers tick a box at checkout on acme.example.",
    "has_links": "NO",
}
ADDRESS = Address(
    customer_name="Acme Inc",
    street="1 Main St",
    city="Austin",
    region="TX",
    postal_code="78701",
    country_code="US",
)


def _provider(handler):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.telnyx.com/v2"
    )
    return TelnyxSmsRegistrationProvider(api_key="k", client=client)


async def _draft(p, subject="business", fields=FIELDS):
    req = await p.requirements("US", "local", subject)
    return await p.create_draft(
        organization_id="org1",
        contact_email="ops@hail.so",
        requirements=req,
        fields=fields,
        address=ADDRESS,
        documents={},
        messaging_service_sid="MP1",
    )


async def test_business_draft_creates_brand_and_requests_vetting() -> None:
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path, json.loads(req.content or b"{}")))
        if req.url.path.endswith("/10dlc/brand"):
            return httpx.Response(
                200, json={"brandId": "B1", "identityStatus": "SELF_DECLARED"}
            )
        if req.url.path.endswith("/vetting"):
            return httpx.Response(200, json={})
        return httpx.Response(404)

    draft = await _draft(_provider(handler))
    assert draft.problems == []
    assert (
        draft.refs["brand_id"] == "B1" and draft.refs["messaging_profile_id"] == "MP1"
    )
    assert draft.refs["subject_type"] == "business"
    assert "Acme" not in repr({k: v for k, v in draft.refs.items() if k != "campaign"})
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/v2/10dlc/brand")
    assert body["entityType"] == "PRIVATE_PROFIT" and body["ein"] == "123456789"
    assert body["country"] == "US" and body["state"] == "TX"
    assert body["website"] == "https://acme.example"
    assert calls[1][:2] == ("POST", "/v2/10dlc/brand/B1/vetting")
    assert calls[1][2] == {"vettingProvider": "AEGIS", "vettingClass": "STANDARD"}


async def test_person_requirements_unsupported() -> None:
    p = _provider(lambda req: httpx.Response(200, json={}))
    with pytest.raises(UnsupportedSubjectType) as exc:
        await p.requirements("US", "local", "person")
    assert exc.value.allowed == ("business",)


async def test_business_requirements_only_business() -> None:
    p = _provider(lambda req: httpx.Response(200, json={}))
    req = await p.requirements("US", "local", "business")
    assert req.subject_types == ("business",)


async def test_missing_field_is_a_problem_and_sends_nothing() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={})

    draft = await _draft(_provider(handler), fields={**FIELDS, "ein": ""})
    assert [p.field for p in draft.problems] == ["ein"]
    assert calls == []


async def test_status_creates_campaign_once_identity_verified() -> None:
    posted = []

    def handler(req):
        if req.url.path.endswith("/10dlc/brand/B1"):
            return httpx.Response(
                200, json={"identityStatus": "VETTED_VERIFIED", "failureReasons": None}
            )
        if req.url.path.endswith("/10dlc/campaignBuilder"):
            posted.append(json.loads(req.content))
            return httpx.Response(200, json={"campaignId": "C1"})
        return httpx.Response(404)

    p = _provider(handler)
    refs = {
        "brand_id": "B1",
        "messaging_profile_id": "MP1",
        "subject_type": "business",
        "campaign": {
            "use_case": "MIXED",
            "description": "d" * 40,
            "message_flow": "f" * 40,
            "samples": ["s" * 20, "t" * 20],
            "has_links": False,
        },
    }
    st = await p.status(refs)
    assert st.state == "pending" and refs["campaign_id"] == "C1"
    assert posted[0]["usecase"] == "MIXED" and posted[0]["brandId"] == "B1"
    assert posted[0]["sample1"] == "s" * 20 and posted[0]["embeddedLink"] is False
    assert posted[0]["optoutKeywords"] == "STOP,STOPALL,UNSUBSCRIBE,CANCEL,END,QUIT"


async def test_status_waits_while_identity_not_verified() -> None:
    posted = []

    def handler(req):
        if req.method == "POST":
            posted.append(req)
        return httpx.Response(200, json={"identityStatus": "UNVERIFIED"})

    p = _provider(handler)
    refs = {"brand_id": "B1", "subject_type": "business", "campaign": {}}
    assert (await p.status(refs)).state == "pending"
    assert posted == [] and "campaign_id" not in refs


async def test_person_draft_is_refused_without_calls() -> None:
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={})

    p = _provider(handler)
    req = (await p.requirements("US", "local", "business")).model_copy(
        update={"subject_type": "person"}
    )
    draft = await p.create_draft(
        organization_id="org1",
        contact_email="ops@hail.so",
        requirements=req,
        fields=FIELDS,
        address=ADDRESS,
        documents={},
    )
    assert draft.refs == {} and len(draft.problems) == 1 and calls == []


async def test_status_rejected_brand() -> None:
    p = _provider(
        lambda req: httpx.Response(
            200, json={"identityStatus": "UNVERIFIED", "failureReasons": "EIN mismatch"}
        )
    )
    st = await p.status({"brand_id": "B1", "subject_type": "business", "campaign": {}})
    assert st.state == "rejected" and "EIN" in st.reason


async def test_status_approved_and_rejected_from_campaign() -> None:
    state = {"campaignStatus": "TCR_ACCEPTED", "failureReasons": None}

    def handler(req):
        if req.url.path.endswith("/10dlc/brand/B1"):
            return httpx.Response(200, json={"identityStatus": "VERIFIED"})
        if req.url.path.endswith("/10dlc/campaign/C1"):
            return httpx.Response(200, json=state)
        return httpx.Response(404)

    p = _provider(handler)
    refs = {
        "brand_id": "B1",
        "messaging_profile_id": "MP1",
        "campaign_id": "C1",
        "subject_type": "business",
        "campaign": {},
    }
    assert (await p.status(refs)).state == "approved"
    state.update({"campaignStatus": "TCR_PENDING"})
    assert (await p.status(refs)).state == "pending"
    state.update(
        {
            "campaignStatus": "TCR_FAILED",
            "failureReasons": "Sample messages missing opt-out language",
        }
    )
    st = await p.status(refs)
    assert st.state == "rejected" and "opt-out" in st.reason


async def test_status_server_error_raises() -> None:
    p = _provider(lambda req: httpx.Response(503))
    with pytest.raises(VerificationProviderError):
        await p.status({"brand_id": "B1", "subject_type": "business", "campaign": {}})


async def test_4xx_gives_neutral_problem_and_cleans_up() -> None:
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/10dlc/brand") and req.method == "POST":
            return httpx.Response(200, json={"brandId": "B1"})
        if req.url.path.endswith("/vetting"):
            return httpx.Response(
                422,
                json={"errors": [{"detail": "Telnyx says the EIN 123456789 is bad"}]},
            )
        return httpx.Response(200, json={})

    draft = await _draft(_provider(handler))
    assert draft.refs == {}
    assert len(draft.problems) == 1
    msg = draft.problems[0].message
    assert "123456789" not in msg and "Telnyx" not in msg
    assert ("DELETE", "/v2/10dlc/brand/B1") in calls


async def test_5xx_raises_and_cleans_up() -> None:
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.url.path.endswith("/10dlc/brand") and req.method == "POST":
            return httpx.Response(200, json={"brandId": "B1"})
        if req.url.path.endswith("/vetting"):
            return httpx.Response(500)
        return httpx.Response(200, json={})

    with pytest.raises(VerificationProviderError):
        await _draft(_provider(handler))
    assert ("DELETE", "/v2/10dlc/brand/B1") in calls


async def test_unexpected_error_cleans_up() -> None:
    calls = []

    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST" and req.url.path.endswith("/10dlc/brand"):
            return httpx.Response(200, json={})  # no brandId
        return httpx.Response(200, json={})

    with pytest.raises(VerificationProviderError):
        await _draft(_provider(handler))


async def test_attach_posts_and_conflict_is_success() -> None:
    calls = []
    status = {"code": 200}

    def handler(req):
        calls.append((req.method, req.url.path, json.loads(req.content)))
        return httpx.Response(status["code"], json={})

    p = _provider(handler)
    await p.attach_number(
        {"campaign_id": "C1"}, provider_resource_id="PN1", e164="+15125550100"
    )
    assert calls[-1] == (
        "POST",
        "/v2/10dlc/phone_number_campaigns",
        {"phoneNumber": "+15125550100", "campaignId": "C1"},
    )
    status["code"] = 409
    await p.attach_number(
        {"campaign_id": "C1"}, provider_resource_id="PN1", e164="+15125550100"
    )
    status["code"] = 500
    with pytest.raises(VerificationProviderError):
        await p.attach_number(
            {"campaign_id": "C1"}, provider_resource_id="PN1", e164="+15125550100"
        )


async def test_discard_order_and_never_raises() -> None:
    calls = []
    codes = {"campaign": 500}

    def handler(req):
        calls.append((req.method, req.url.path))
        if "/campaign/" in req.url.path:
            return httpx.Response(codes["campaign"], json={})
        return httpx.Response(200, json={})

    p = _provider(handler)
    await p.discard({"brand_id": "B1", "campaign_id": "C1"})
    assert calls == [
        ("DELETE", "/v2/10dlc/campaign/C1"),
        ("DELETE", "/v2/10dlc/brand/B1"),
    ]
    codes["campaign"] = 404
    await p.discard({"brand_id": "B1", "campaign_id": "C1"})
    await p.discard({})
