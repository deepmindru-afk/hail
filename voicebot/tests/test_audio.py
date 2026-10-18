"""Audio filtering stays on the agent input; it never republishes a track."""

from types import SimpleNamespace

from hailhq.core.config import settings
from hailhq.voicebot.audio import room_options
from livekit import rtc


def test_cloud_sip_uses_telephony_voice_isolation(monkeypatch):
    monkeypatch.setattr(settings, "livekit_url", "wss://test.livekit.cloud")
    monkeypatch.setattr(settings, "hail_voice_noise_cancellation", True)
    selector = room_options().audio_input.noise_cancellation
    option = selector(
        SimpleNamespace(
            participant=SimpleNamespace(kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP)
        )
    )
    assert option is not None
    assert "inb.bvc" in option.options["modelPath"]


def test_self_hosted_transport_does_not_request_cloud_filter(monkeypatch):
    monkeypatch.setattr(settings, "livekit_url", "wss://livekit.example.org")
    assert room_options().audio_input.noise_cancellation is None


def test_operator_can_disable_cloud_filter(monkeypatch):
    monkeypatch.setattr(settings, "livekit_url", "wss://test.livekit.cloud")
    monkeypatch.setattr(settings, "hail_voice_noise_cancellation", False)
    assert room_options().audio_input.noise_cancellation is None
