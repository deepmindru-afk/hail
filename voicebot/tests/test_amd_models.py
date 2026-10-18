"""Multilingual AMD must not override a customer's provider selection."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from hailhq.core.config import settings
from hailhq.voicebot import amd
from hailhq.voicebot.pipeline import ResolvedLayer


@pytest.fixture
def layers(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "house-openai")
    monkeypatch.setattr(settings, "google_api_key", "house-google")
    session = SimpleNamespace(llm=object(), stt=object(), vad=object())
    transcribe = Mock(return_value=object())
    google = Mock(return_value=object())
    monkeypatch.setattr(amd.openai, "STT", transcribe)
    monkeypatch.setattr(amd.google, "LLM", google)
    return session, transcribe, google


def test_house_greeting_transcription_does_not_pin_the_call_language(layers):
    session, transcribe, google = layers
    result = amd.build_amd_models(session, language="en")
    assert result.stt is not session.stt
    assert transcribe.call_args.kwargs["model"] == "gpt-live-transcribe"
    assert transcribe.call_args.kwargs["detect_language"] is True
    assert transcribe.call_args.kwargs["vad"] is session.vad
    assert google.call_args.kwargs["model"] == "gemini-3.1-flash-lite"


def test_byo_layers_keep_the_orgs_providers(layers):
    session, transcribe, google = layers
    orgs = {
        "stt": ResolvedLayer("speechmatics", "org-stt", {}, False),
        "llm": ResolvedLayer("anthropic", "org-llm", {}, False),
    }
    result = amd.build_amd_models(session, org_cfgs=orgs, language="fr")
    assert result.llm is session.llm
    assert result.stt is session.stt
    transcribe.assert_not_called()
    google.assert_not_called()


def test_per_call_llm_remains_the_amd_brain(layers):
    session, _, google = layers
    result = amd.build_amd_models(session, llm_override=True)
    assert result.llm is session.llm
    google.assert_not_called()


@pytest.mark.parametrize(
    "language,expected", [("fr", "multi"), ("ar", "ar"), ("da", "da")]
)
def test_byo_deepgram_multilingual_coverage_is_respected(
    layers, monkeypatch, language, expected
):
    session, transcribe, _ = layers
    build = Mock(return_value=object())
    monkeypatch.setattr(amd, "build_stt", build)
    org = ResolvedLayer("deepgram", "org-key", {"model": "nova-3"}, False)
    amd.build_amd_models(session, org_cfgs={"stt": org}, language=language)
    transcribe.assert_not_called()
    build.assert_called_once_with(org, language=expected, provider="deepgram")


def test_missing_house_credentials_keep_the_existing_pipeline(layers, monkeypatch):
    session, transcribe, google = layers
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "google_api_key", "")
    result = amd.build_amd_models(session)
    assert result.stt is session.stt and result.llm is session.llm
    transcribe.assert_not_called()
    google.assert_not_called()


def test_optional_stt_setup_failure_keeps_the_working_session_stt(layers):
    session, transcribe, _ = layers
    transcribe.side_effect = ValueError("speech account not configured")
    result = amd.build_amd_models(session)
    assert result.stt is session.stt


def test_optional_classifier_setup_failure_keeps_the_working_session_llm(layers):
    session, _, google = layers
    google.side_effect = ValueError("classifier account not configured")
    result = amd.build_amd_models(session)
    assert result.llm is session.llm


async def test_only_amd_owned_models_are_closed(layers):
    from unittest.mock import AsyncMock

    session, transcribe, google = layers
    owned = SimpleNamespace(aclose=AsyncMock())
    transcribe.return_value = owned
    result = amd.build_amd_models(session, llm_override=True)
    await result.aclose()
    owned.aclose.assert_awaited_once()
    google.assert_not_called()


async def test_real_provider_constructors_support_independent_autodetection(
    monkeypatch,
):
    from livekit.agents import AgentSession
    from livekit.plugins import deepgram, openai

    from ._fakes import FakeLLM

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test-placeholder")
    monkeypatch.setattr(settings, "google_api_key", "google-test-placeholder")
    session = AgentSession(
        vad=Mock(),
        llm=FakeLLM(),
        stt=deepgram.STT(api_key="deepgram-test-placeholder", language="en"),
    )
    models = amd.build_amd_models(session, language="en")
    try:
        assert isinstance(models.stt, openai.STT)
        assert models.stt.model == "gpt-live-transcribe"
        assert models.stt._opts.languages == []  # wire config must not force English
        assert models.stt._vad is session.vad
        assert models.stt is not session.stt
    finally:
        await models.aclose()
        await models.aclose()  # safe when detection and shutdown both clean up
