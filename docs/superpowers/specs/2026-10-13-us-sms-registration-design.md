# US SMS registration (A2P 10DLC) per customer: design

Date: 2026-10-13. Status: approved in conversation, pending spec review.

## Goal

A customer registers their own A2P 10DLC brand and campaign with the carrier
from the Hail console, API, or MCP. Hail files it, pays the carrier fee from
the customer's prepaid credit, and attaches the customer's US numbers once
the carrier approves. Until then, texts from a US long code to a US number
get a clear error.

This replaces the shared Hail-owned campaign model from
`2026-07-06-sms-support-design.md` Decision 2. That campaign was never
approved (Twilio rejected it on 2026-07-09, error 30919). `abuse_monitor.py`
keeps working but its docstring is updated: the guardrail now protects
Hail's carrier account standing, not a shared campaign.

Out of scope for this release: toll-free verification, DIDWW (voice only,
no SMS through Hail), Canada.

## Decisions (owner, 2026-10-13)

1. Scope: 10DLC on long codes, business and person (sole proprietor),
   Twilio and Telnyx.
2. Fees: customer pays carrier cost from prepaid credit. No markup.
3. Gate: US-to-US sends from an unregistered long code return 422.
4. Surfaces: console, API, MCP, CLI.
5. Build: extend the carrier verification framework, no new subsystem.

## Model

`carrier_verifications` gains `purpose TEXT NOT NULL DEFAULT 'number'`
with `CHECK (purpose IN ('number','sms'))`. The live-uniqueness index
adds `purpose`. An SMS row has `country_code='US'`, `number_type='local'`,
one live row per organization per carrier.

`provider_refs` for an SMS row (opaque, never shown):

- Twilio: `profile_sid`, `trust_bundle_sid`, `brand_sid`,
  `messaging_service_sid`, `campaign_sid`.
- Telnyx: `brand_id`, `campaign_id`, `messaging_profile_id`.

No names, EINs, addresses, or phone numbers are stored by Hail. The
carrier holds them.

States reuse the existing set. Meaning for `purpose='sms'`:

| State             | Meaning                                                               |
| ----------------- | --------------------------------------------------------------------- |
| `awaiting_review` | Profile and brand created at the carrier, not yet submitted.          |
| `submitting`      | Hail is submitting the brand.                                         |
| `submitted`       | Brand in vetting, or brand approved and campaign in carrier review.   |
| `approved`        | Campaign approved. Numbers attached. US texting works.                |
| `rejected`        | Brand or campaign refused. `rejection_reason` carries the carrier's text. |
| `cancelled`       | Customer withdrew or dismissed.                                       |

## Carrier plug-ins

Two new `VerificationProvider` implementations, registered under the
existing carrier names with `purpose='sms'`: one for Twilio, one for
Telnyx. Same contract: `requirements`, `create_draft`, `check`, `submit`,
`status`, `purchase_handle`, `discard`. Carrier words (brand, campaign,
trust bundle, profile) stay inside the plug-in.

`requirements(country_code='US', number_type='local', subject_type)`
returns:

- Business: legal name, business type (private, public, non-profit,
  government), EIN, industry, website, address, authorized representative
  (name, email, phone, title).
- Person: first name, last name, email, mobile number, address.
- Both: campaign description, two sample messages, opt-in description
  (how the recipient agreed), embedded links yes/no.
- No document slots. `needs_input` is true for every field.

Hail adds fixed campaign values the customer does not type: use case
(business: `MIXED`; person: `SOLE_PROPRIETOR`), opt-out and help keywords
(STOP/HELP, already honored platform-wide), help message, and the message
flow text, built from the opt-in description.

`create_draft`:

- Twilio: create Secondary Customer Profile (business) or Starter Profile
  (person), end users, address, trust bundle; evaluate; submit profile and
  bundle; create brand. Create one messaging service per organization if
  none exists (`sms_setup.py` already does this; reuse).
- Telnyx: create brand. Messaging profile per organization already exists
  (`sms_setup.py`).

`submit`: Twilio brand registration is created in `create_draft` and
vetting starts on creation; `submit` is a no-op that records
`submitted_at`. Telnyx: request vetting.

`status`:

- Brand pending or in review → `submitted`.
- Brand failed → `rejected` with the carrier's reason.
- Brand approved and no campaign yet → create the campaign (Twilio:
  `Compliance/Usa2p` on the org's messaging service; Telnyx:
  `campaignBuilder`), stay `submitted`.
- Campaign pending → `submitted`.
- Campaign failed → `rejected` with the carrier's reason.
- Campaign approved → attach every active US long code of this
  organization on this carrier (Twilio: number already sits in the
  messaging service, campaign covers the service; Telnyx:
  `phoneNumberCampaign` per number), then `approved`.

Person flow: the carrier texts the person a confirmation link after brand
creation. The person taps it. `status` sees the brand move to approved.
The console copy says: "Check your phone. Tap the link in the text from
the carrier." A mobile number can be used for three brands in its lifetime
(carrier rule). The form says so.

`discard`: delete the campaign, brand, bundle, and profile that exist, in
that order, ignoring already-deleted errors. Not allowed from `submitted`
(409, same rule as number verification).

`purchase_handle`: returns `{}`. Numbers are not gated by SMS registration
at purchase time.

## Fees

Carrier fees, read from `costs/sms-registration.json` (new file, same
shape and refresh job as `costs/sms.json`):

| Item                         | Twilio (2026-08) | Telnyx           |
| ---------------------------- | ---------------- | ---------------- |
| Brand, person                | $4.50 once       | from catalog     |
| Brand, business, with vetting | $46 once        | from catalog     |
| Campaign vetting             | $15 once         | from catalog     |
| Campaign, person             | $2 per month     | from catalog     |
| Campaign, business (mixed)   | $10 per month    | from catalog     |

Hail debits `account_credits` (`kind='debit'`, `channel='sms'`) at
`create_draft` for brand plus campaign vetting, in the same transaction
that saves the row, as `number_orders.py` does for the setup fee. If the
balance cannot cover it, `POST /verifications` returns 402 before anything
is created at the carrier. A rejected brand is not refunded (the carrier
does not refund Hail). A rejected campaign refunds the campaign vetting
fee only if the carrier refunds Hail.

Monthly campaign fee: `hail-website/lib/monthly-fee-rater.ts` adds a
`sms_registration` line next to number rent, charged on the day of month
the campaign was approved. The audit log carries the fee amounts.

The console shows the total before the customer submits: "Filing costs
$61 now and $10 per month after approval. Paid from your credit."

## Send gate

`POST /sms` (route in `api/hailhq/api/routes/sms.py`), after the
from-number is resolved and before the carrier call:

- If `to` starts with `+1`, the from-number is a `+1` long code (not
  toll-free), and the organization has no `approved` SMS row for that
  number's carrier → 422, `loc=["body","from"]`,
  "US texting from this number needs SMS registration. Open Numbers in the
  console and choose Register for US texting."
- Toll-free from-numbers, non-US destinations, and Sender ID sends are
  unchanged.

Inbound SMS is unchanged. Account-notification SMS from Hail to its own
users (`sender_id_sms_carrier`) is unchanged; Hail's own registration is an
operator task, not this feature.

## Number attach

- Approval attaches every active US long code of the org on that carrier
  (see `status`).
- A US long code that becomes active later, on an org with an `approved`
  row for its carrier, is attached in `sms_setup.py` right after it joins
  the messaging service or profile.
- Number release: Twilio needs nothing; Telnyx removes the
  `phoneNumberCampaign` link in the existing release path.

## API, CLI, MCP

- `GET /verifications/requirements` and `POST /verifications` take
  `purpose` (default `number`). `GET /verifications` and the response
  model expose `purpose`.
- OpenAPI regenerated; CLI client regenerated; `hail verification` gains
  `--purpose sms`.
- MCP: the verification tools from hail-hq/hail#172 gain `purpose`. If
  #172 is not merged when this ships, the SMS tools wait for it.
- Docs: `docs/public/numbers.md` (or the page that documents
  verifications) gets a "US texting" section with one runnable curl.

## Console (hail-website)

- Numbers page: a "US texting" card per carrier that has US long codes on
  the org. States: Not registered (button "Register for US texting"),
  In review (date filed, "1 to 7 business days"), Approved (date),
  Rejected (carrier reason, button "Try again").
- The existing `VerificationWizard` renders the form from `requirements()`
  with `purpose='sms'`. Person vs business toggle stays. Fee line above
  the submit button.
- Superadmin `/console/admin/verifications` lists SMS rows with the same
  approve and reject actions.
- Legal: Privacy §2 and §3.1 already cover verification data filed with
  the carrier. `facts.md` gets the fee pass-through fact.

## Background pass

`sweep_verifications` already retries submits and refreshes status. SMS
rows ride it. Campaign creation and number attach happen inside `status`,
so a crash mid-way is retried on the next pass. Each step checks
`provider_refs` before acting, so no duplicate brands or campaigns.

## Errors

- Carrier down at `create_draft`: 503, nothing stored, nothing charged.
- Carrier rejects a field at `create_draft`: 422 with the field name,
  nothing stored, nothing charged.
- Insufficient credit: 402 before any carrier call.
- Brand or campaign rejected: row `rejected`, reason shown verbatim from
  the carrier, customer can dismiss and file again (new fee).

## Testing

- `api/tests/test_verifications_api.py`: `FakeCarrier` gains
  `purpose='sms'` behavior (brand → campaign → attach state machine).
  Tests: create with fee debit, 402 on low balance, person link flow,
  campaign created on brand approval, numbers attached on campaign
  approval, rejection reasons, discard order, 409 on discard while
  submitted.
- `api/tests/test_sms_api.py`: 422 gate for US-to-US from an unregistered
  long code; pass for toll-free, non-US, Sender ID, and registered orgs.
- `core/tests`: each plug-in's request bodies against recorded carrier
  responses (no live calls).
- hail-website: wizard renders SMS requirements; fee line; card states.

## Operator prerequisites (before the first customer files)

- Twilio: Hail's primary customer profile must carry business identity
  "ISV Reseller or Partner" and be approved. Today it is a plain approved
  business profile; the identity is changed in the Twilio console, Trust
  Hub. The failed campaign `QE2c6890da8086d771620e9b13fadeba0b` is deleted.
- Telnyx: nothing; brands are created under Hail's account directly.

## Rollout

1. Migration adds `purpose` (default `number`, existing rows unaffected).
2. Deploy API with the gate behind `HAIL_SMS_REGISTRATION_GATE=off` for
   one release, so existing US senders are not cut off before they can
   register. Console shows the card at once.
3. Email existing orgs with US long codes: register within 30 days.
4. Flip the gate on.
