"""Agent-input filtering, separate from room recording and published tracks.

Verified with Agents 1.8.8:
https://docs.livekit.io/transport/media/noise-cancellation/
"""

from __future__ import annotations

from importlib import import_module

from hailhq.core.config import settings
from livekit import rtc
from livekit.agents import room_io
from livekit.agents.utils.misc import is_cloud


def prewarm_audio() -> None:
    """Load the native Cloud filter before the job's event loop serves a call."""
    if is_cloud(settings.livekit_url):
        import_module("livekit.plugins.noise_cancellation")


def room_options() -> room_io.RoomOptions:
    selector = None
    if is_cloud(settings.livekit_url):
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
