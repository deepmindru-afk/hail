"""Latency comes from committed SDK messages, never the deprecated session event."""

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from hailhq.voicebot.agent import attach_event_handlers
from livekit.agents import AgentSession
from livekit.agents.llm import ChatMessage
from livekit.agents.voice.events import ConversationItemAddedEvent


async def test_committed_turns_store_supported_latency_metrics(monkeypatch, caplog):
    recorded = []

    async def write(_call_id, kind, payload):
        recorded.append((kind, payload))

    monkeypatch.setattr("hailhq.voicebot.agent.write_call_event", write)
    session = AgentSession()
    tasks = attach_event_handlers(session, UUID(int=1))
    user = ChatMessage(
        role="user",
        content=["private speech"],
        metrics={"transcription_delay": 0.1, "end_of_turn_delay": 0.4},
    )
    reply = ChatMessage(
        role="assistant",
        content=["Hello."],
        metrics={
            "llm_node_ttft": 0.25,
            "tts_node_ttfb": 0.08,
            "e2e_latency": 0.75,
            "playback_latency": 0.02,
        },
    )
    for item in (user, reply):
        session.emit("conversation_item_added", ConversationItemAddedEvent(item=item))
    await asyncio.gather(*list(tasks))
    metrics = [payload for kind, payload in recorded if kind == "voice_metrics"]
    assert metrics == [
        {
            "message_id": user.id,
            "role": "user",
            "transcription_delay": 0.1,
            "end_of_utterance_delay": 0.4,
        },
        {
            "message_id": reply.id,
            "role": "assistant",
            "ttft": 0.25,
            "ttfb": 0.08,
            "e2e_latency": 0.75,
            "playback_latency": 0.02,
        },
    ]
    assert "metrics_collected is deprecated" not in caplog.text
    assert "metrics_collected" not in session._events


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, True, "0.2"])
async def test_invalid_or_private_metrics_are_not_written(monkeypatch, invalid):
    recorded = []

    async def write(_call_id, kind, payload):
        recorded.append((kind, payload))

    monkeypatch.setattr("hailhq.voicebot.agent.write_call_event", write)
    session = AgentSession()
    tasks = attach_event_handlers(session, UUID(int=1))
    item = SimpleNamespace(
        id="message-1",
        role="assistant",
        text_content="Hello.",
        metrics={
            "llm_node_ttft": invalid,
            "tts_node_ttfb": 0,
            "transcript": "private speech",
            "api_key": "private key",
        },
    )
    session.emit("conversation_item_added", SimpleNamespace(item=item))
    await asyncio.gather(*list(tasks))
    assert [payload for kind, payload in recorded if kind == "voice_metrics"] == [
        {"message_id": "message-1", "role": "assistant", "ttfb": 0}
    ]


async def test_final_user_turn_keeps_timings_without_an_assistant_reply(monkeypatch):
    recorded = []

    async def write(_call_id, kind, payload):
        recorded.append((kind, payload))

    monkeypatch.setattr("hailhq.voicebot.agent.write_call_event", write)
    session = AgentSession()
    tasks = attach_event_handlers(session, UUID(int=1))
    item = ChatMessage(
        role="user", content=["Bye."], metrics={"end_of_turn_delay": 2.5}
    )
    session.emit("conversation_item_added", ConversationItemAddedEvent(item=item))
    await asyncio.gather(*list(tasks))
    assert recorded[-1] == (
        "voice_metrics",
        {"message_id": item.id, "role": "user", "end_of_utterance_delay": 2.5},
    )
