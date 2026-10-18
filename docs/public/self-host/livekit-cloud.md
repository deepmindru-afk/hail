# LiveKit Cloud

LiveKit Cloud supplies the media (SIP bridge + WebRTC) in v1. A self-hosted SFU is a later milestone.

## 1. Project + keys

1. Sign up at [cloud.livekit.io](https://cloud.livekit.io).
2. Create a project.
3. From **Settings → Keys**, copy these values into `.env`:
   - `LIVEKIT_URL` — `wss://<project>-<region>.livekit.cloud`
   - `LIVEKIT_API_KEY`
   - `LIVEKIT_API_SECRET`

## 2. SIP outbound trunk

First create the Twilio trunk and credentials in the [Twilio guide](./twilio.md).
Then, in LiveKit Cloud:

1. Open **Telephony → SIP trunks → Create new trunk**.
2. Select **Outbound** and use the Twilio termination domain
   (`<name>.pstn.twilio.com`) as the address.
3. Add the Twilio number in E.164 format and enter the same username/password
   configured on the Twilio trunk.
4. Create the trunk and copy its ID into `.env` as
   `LIVEKIT_TWILIO_SIP_OUTBOUND_TRUNK_ID`.

Hail passes this ID to LiveKit for every outbound call from a Twilio number.
The older `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` name remains supported as a
compatibility alias; the explicit Twilio name takes precedence. Numbers from
another carrier use their own trunk: see [DIDWW](./didww.md) and
`LIVEKIT_TELNYX_SIP_OUTBOUND_TRUNK_ID`. Hail does not read a Twilio
trunk-domain environment variable. See LiveKit's
[outbound trunk reference](https://docs.livekit.io/telephony/making-calls/outbound-trunk/)
for the current UI and JSON forms.

## 3. Voicebot worker

With the local Compose overlay, run:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d voicebot
```

At startup, the worker registers with LiveKit as a dispatchable agent. The
Hail API dispatches it into a room for each call.

For the full flow, refer to [Architecture](../architecture.md).

The worker uses Agents 1.8.8 and the built-in audio turn detector (local mini
model on a VM). Speechmatics uses Linden-1; legacy `operating_point` inputs
normalize to `model=linden-1`. The API waits up to 20 seconds for audio readiness
before dialing. API and worker must therefore run the same release.

Voice controls in `.env` (restart the worker after changing them):

- `HAIL_VOICE_NOISE_CANCELLATION=true`: Krisp BVC Telephony on Cloud SIP input.
  This filters the agent's input only; room tracks and Egress recording stay intact.
- `HAIL_VOICE_INTERRUPTION_MODE=auto`: SDK availability checks. Use `adaptive`
  only with supported Cloud access; `vad` forces the local fallback.
- `HAIL_VOICE_RECOVERY_TIMEOUT_SECONDS=20`: after no transcript progress, ask
  the caller to repeat once, then end if the next interval also has no progress.
  Paused during agent speech, tool work, IVR, and human handover. `0` disables it.
- `HAIL_AMD_MULTILINGUAL=true`: house AMD uses `gpt-live-transcribe` with
  explicit language detection and `gemini-3.1-flash-lite`, through house provider
  keys. BYO layers retain their providers; Speechmatics BYO retains its configured
  language, and Deepgram multi covers ten languages. `false` reuses session layers.

`call_events` includes numeric `voice_metrics` (LLM/TTS/endpoint timing) and AMD
reason/delay. Before rollout, compare median/p95 timing and replay noisy and
multilingual greetings, including false voicemail detections on real people.
Rebase voice changes after the recording PR merges and rerun its lifecycle tests.


## 4. Inbound calls

Hail answers calls on a number once the number routes calls to an agent
([Agents](../agents.md)). LiveKit needs **one inbound trunk** and **one
dispatch rule**. Hail adds and removes numbers on the trunk itself.

1. Inbound trunk. One trunk for every carrier: LiveKit allows a single
   wildcard (empty `numbers`) inbound trunk per project. Without `numbers`,
   LiveKit needs `allowed_addresses` (or `auth_username`/`auth_password`,
   which Twilio Elastic SIP does not send). The carrier pages say what each
   carrier sends: [Twilio](./twilio.md#6-inbound-calls),
   [Telnyx](./telnyx.md#inbound-calls), [DIDWW](./didww.md#inbound-calls).

   ```bash
   cat > inbound.json <<'JSON'
   {"trunk": {"name": "hail-inbound", "numbers": [], "allowed_addresses": ["0.0.0.0/0"]}}
   JSON
   lk sip inbound create inbound.json
   # → ST_...  → LIVEKIT_SIP_INBOUND_TRUNK_ID
   ```

   Hail reads the dialed number from the call and finds its carrier in
   `phone_numbers`; the trunk does not need to know it. To lock each carrier
   to its own trunk instead, create one trunk per carrier with that
   carrier's signaling IPs in `allowed_addresses` and set
   `LIVEKIT_<CARRIER>_SIP_INBOUND_TRUNK_ID` (an override not listed in
   `.env.example`) to that trunk's id. Narrow `0.0.0.0/0` to the carriers' IP ranges when you can.

2. Dispatch rule. One rule, bound to the inbound trunk, that puts each
   caller in its own room and dispatches the voicebot with the static
   metadata it expects:

   ```bash
   cat > dispatch-rule.json <<'JSON'
   {
     "dispatch_rule": {
       "name": "hail-inbound",
       "trunk_ids": ["<inbound-trunk-id>"],
       "rule": {"dispatchRuleIndividual": {"roomPrefix": "hail-in-"}},
       "roomConfig": {
         "agents": [{"agentName": "hail-voicebot", "metadata": "{\"direction\":\"inbound\"}"}]
       }
     }
   }
   JSON
   lk sip dispatch create dispatch-rule.json
   ```

   Room names include the caller's number (LiveKit's individual rule);
   `calls.from_e164` records it anyway.

3. Set the trunk id in `.env` and recreate `api` and `voicebot`. Then
   `PATCH /v1/numbers/{id}` with `voice_agent_id` registers a number
   ([Agents](../agents.md#routing-rules)).

Reference: LiveKit [accepting calls](https://docs.livekit.io/telephony/accepting-calls/),
[inbound trunk](https://docs.livekit.io/telephony/accepting-calls/inbound-trunk/),
[dispatch rule](https://docs.livekit.io/telephony/accepting-calls/dispatch-rule/).
