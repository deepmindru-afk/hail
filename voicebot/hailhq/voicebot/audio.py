"""Agent-input filtering, separate from room recording and published tracks.

Verified with Agents 1.8.8:
https://docs.livekit.io/transport/media/noise-cancellation/
"""

from __future__ import annotations

from urllib.parse import urlsplit

from hailhq.core.config import settings
from livekit import rtc
from livekit.agents import room_io


def room_options() -> room_io.RoomOptions:
    host = urlsplit(settings.livekit_url).hostname or ""
    selector = None
    if settings.hail_voice_noise_cancellation and host.endswith(".livekit.cloud"):
        # Proprietary Cloud filter, loaded only for the supported transport.
        # It processes subscribed input frames without republishing cleaned audio;
        # composite Egress continues to capture the original room tracks.
        from livekit.plugins import noise_cancellation

        def selector(params):
            if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
                return noise_cancellation.BVCTelephony()
            return noise_cancellation.BVC()

    return room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(noise_cancellation=selector)
    )
