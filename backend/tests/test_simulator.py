"""The simulator host: it reaches Greeo only through MCP, in mock and LLM modes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from apps.core.models import StageTrace
from apps.llm.backends import BedrockLLM, ToolCall, ToolTurn, parse_tool_turn
from apps.llm.client import LLMGateway
from apps.llm.exceptions import LLMProviderError
from apps.llm.models import LLMCall
from apps.mcp_server.server import create_app
from apps.memory.models import StoryEncounter
from apps.simulator import host as host_module
from apps.simulator import speech
from apps.simulator.host import (
    NOTHING_SAID,
    THINKING_TROUBLE,
    UNREACHABLE,
    configured_host,
    run_turn,
)
from apps.simulator.llm_host import LLMHost
from apps.simulator.mcp_link import McpLink
from apps.simulator.mock_host import MockHost, pick_listed_story, search_query, tone_in
from apps.simulator.state import SessionStore
from apps.stories.models import Story
from django.test import override_settings
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from rest_framework.test import APIClient

from tests.test_mcp_server import BASE

pytestmark = pytest.mark.django_db
USER = {"X-Greeo-User": "sim-listener"}


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int) -> bool:
        self.values[key] = value
        return True

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)


@asynccontextmanager
async def in_process(credentials: dict[str, str]):
    """The real MCP server, in-process, over its real HTTP transport."""
    app = create_app()
    headers = dict(credentials)
    async with app.router.lifespan_context(app):
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers
        )
        transport = streamable_http_client(f"{BASE}/mcp", http_client=http)
        async with http, Client(transport, mode="legacy") as client:
            yield McpLink(client)


@pytest.fixture(autouse=True)
def simulator(settings, monkeypatch) -> SessionStore:
    """DEBUG on for the dev identity; MCP in-process; session state in memory."""
    settings.DEBUG = True
    settings.MCP_ALLOW_DEV_IDENTITY = True
    store = SessionStore(client=FakeRedis())
    monkeypatch.setattr(host_module, "connect", in_process)
    monkeypatch.setattr(host_module, "SessionStore", lambda: store)

    async def no_network(credentials: dict[str, str]) -> None:
        return None

    monkeypatch.setattr(host_module, "http_status", no_network)
    return store


def say(text: str, session: str = "s1", **kwargs: Any):
    return run_turn(session, text, USER, **kwargs)


def tools_called(result) -> list[str]:
    return [step["tool"] for step in result.tool_trace]


class ScriptedGateway:
    """Stands in for the LLM gateway: returns prepared turns and records what it was sent."""

    def __init__(self, turns: list[ToolTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def generate_with_tools(self, prompt_name, messages, tools, run_id="simulator") -> ToolTurn:
        self.requests.append({"prompt": prompt_name, "messages": list(messages), "tools": tools})
        return self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]


def wants(tool: str, **arguments: Any) -> ToolTurn:
    call = ToolCall(id=f"call-{tool}", name=tool, arguments=arguments)
    message = {"role": "assistant", "content": [{"toolUse": {"toolUseId": call.id, "name": tool}}]}
    return ToolTurn(text="", tool_calls=(call,), assistant_message=message)


def says(text: str) -> ToolTurn:
    message = {"role": "assistant", "content": [{"text": text}]}
    return ToolTurn(text=text, tool_calls=(), assistant_message=message)


# The mock host -------------------------------------------------------------------------


def test_mock_host_walks_the_whole_tale_through_mcp(story: Story) -> None:
    topic = say("tell me about the footbridge")
    assert tools_called(topic) == ["search_events", "tell_tale"]
    assert topic.host_mode == "mock"
    assert topic.display["resource_uri"] == "ui://greeo/tale"
    assert topic.display["structured"]["beat"] == 1

    assert say("go on").display["structured"]["beat"] == 2
    last = say("go on")
    assert last.display["structured"]["has_more"] is False

    steps = [
        ("what's the lesson?", ["get_moral"]),
        ("what does that proverb mean?", ["explain_proverb"]),
        ("what actually happened?", ["get_facts"]),
        ("why does it matter?", ["get_context"]),
        ("what are the sides?", ["get_perspectives"]),
        ("show me the evidence", ["get_sources"]),
        ("save it", ["save_for_later"]),
    ]
    for text, expected in steps:
        result = say(text)
        assert tools_called(result) == expected, text
        assert all(step["ok"] and step["ms"] >= 0 for step in result.tool_trace)

    assert say("what's the lesson?").spoken == "A crossing built together is carried together."


def test_tale_beat_text_is_returned_unchanged(story: Story) -> None:
    result = say("tell me about the footbridge")

    assert result.spoken == result.display["structured"]["text"]
    assert "Test proverb one is spoken here." in result.spoken


def test_changing_tone_sets_the_preference_and_retells(story: Story) -> None:
    say("tell me about the footbridge")

    result = say("make it serious")

    assert tools_called(result) == ["set_preferences", "tell_tale"]
    assert result.display["structured"]["tone_served"] == "serious"
    assert result.display["structured"]["beat"] == 1


def test_interrupting_a_tale_keeps_progress(story: Story) -> None:
    say("tell me about the footbridge")

    facts = say("wait, what actually happened?")
    resumed = say("continue")

    assert tools_called(facts) == ["get_facts"]
    assert resumed.display["structured"]["beat"] == 2
    assert StoryEncounter.objects.get(story=story).last_beat == 2


def test_fresh_session_recalls_the_saved_story_with_a_resume_hint(story: Story) -> None:
    say("tell me about the footbridge", session="first")
    say("go on", session="first")
    say("save it", session="first")

    recalled = say("what was I listening to?", session="second")

    assert tools_called(recalled) == ["get_saved_stories"]
    assert "continue at beat 3" in recalled.spoken
    assert say("the first one", session="second").display["structured"]["story_id"] == story.pk


def test_tool_errors_surface_as_friendly_replies(story: Story) -> None:
    no_story = say("go on", session="empty")
    no_match = say("tell me about volcanoes", session="empty")

    assert tools_called(no_story) == ["tell_tale"] and no_story.tool_trace[0]["ok"] is False
    assert no_story.spoken.startswith("Which story would you like?")
    assert no_story.display["is_error"] is True and no_story.display["resource_uri"] is None
    assert "couldn't find a story about volcanoes" in no_match.spoken


def test_briefing_then_choosing_by_position(story: Story) -> None:
    listing = say("what's going on?")
    chosen = say("the first one")

    assert tools_called(listing) == ["get_briefing"]
    assert tools_called(chosen) == ["tell_tale"]


def test_start_over_clears_the_conversation(story: Story, simulator: SessionStore) -> None:
    say("tell me about the footbridge")
    assert simulator.load("s1").last_story_id == story.pk

    result = say("start over")

    assert tools_called(result) == ["set_preferences"]
    assert result.spoken.startswith("Starting fresh.")
    assert simulator.load("s1").last_story_id is None


def test_help_needs_no_tool() -> None:
    result = say("what can you do?")

    assert result.tool_trace == [] and "short tales" in result.spoken


def test_every_turn_is_traced_with_its_host_mode(story: Story) -> None:
    say("tell me about the footbridge")

    trace = StageTrace.objects.get(stage="simulator_turn")
    assert (trace.host_mode, trace.status) == ("mock", StageTrace.Status.OK)
    assert trace.output_summary == "search_events, tell_tale"


def test_router_helpers() -> None:
    assert tone_in("make it serious") == "serious"
    assert tone_in("lighter please") == "light"
    assert tone_in("news about light rail") is None
    assert search_query("tell me about the footbridge") == "the footbridge"
    listed = [
        {"story_id": "st_a", "title": "The Lantern Footbridge"},
        {"story_id": "st_b", "title": "X"},
    ]
    assert pick_listed_story("the second one", listed) == "st_b"
    assert pick_listed_story("the lantern footbridge", listed) == "st_a"
    assert pick_listed_story("something else", listed) is None


def test_mcp_being_unreachable_is_a_friendly_reply() -> None:
    @asynccontextmanager
    async def broken(user):
        raise ConnectionError("synthetic outage")
        yield

    result = run_turn("s1", "what's going on?", USER, connector=broken)

    assert result.spoken == UNREACHABLE and result.tool_trace == []
    assert StageTrace.objects.get().status == StageTrace.Status.FAILED


# The LLM host --------------------------------------------------------------------------


def test_llm_host_delivers_tool_text_unchanged_not_the_models_paraphrase(story: Story) -> None:
    gateway = ScriptedGateway(
        [wants("tell_tale", story_id=story.pk, beat=1), says("Here is my own summary instead.")]
    )

    result = say("tell me the story", host=LLMHost(gateway=gateway))

    assert result.host_mode == "llm"
    assert tools_called(result) == ["tell_tale"]
    assert result.spoken == result.display["structured"]["text"]
    assert "my own summary" not in result.spoken
    assert gateway.requests[0]["prompt"] == "simulator_host"
    assert {tool["name"] for tool in gateway.requests[0]["tools"]} >= {"tell_tale", "get_facts"}
    fed_back = gateway.requests[1]["messages"][-1]["content"][0]["toolResult"]
    assert fed_back["status"] == "success" and fed_back["content"][0]["json"]["beat"] == 1


def test_llm_host_stops_at_the_iteration_cap(story: Story) -> None:
    gateway = ScriptedGateway([wants("get_facts", story_id=story.pk)])

    with override_settings(SIMULATOR_MAX_TOOL_ITERATIONS=4):
        result = say("loop forever", host=LLMHost(gateway=gateway))

    assert len(gateway.requests) == 4
    assert tools_called(result) == ["get_facts"] * 4
    assert result.spoken.startswith("SYNTHETIC. Residents of Veloria")


def test_llm_host_reply_without_tools_is_kept_short_and_safe() -> None:
    chatty = says(" ".join(f"Sentence {n} here." for n in range(60)))
    jargon = says("The JSON from the API is null.")

    long_reply = say("hello", host=LLMHost(gateway=ScriptedGateway([chatty])))
    unsafe = say("hello", host=LLMHost(gateway=ScriptedGateway([jargon])))

    assert len(long_reply.spoken.split()) <= 75
    assert unsafe.spoken == NOTHING_SAID


def test_llm_host_answering_a_story_question_without_tools_is_overruled(story: Story) -> None:
    """Seen live with Nova Lite: facts recited from earlier turns, no tool called."""
    say("tell me about the footbridge")
    from_memory = says("From what I recall, the bridge cost a fortune.")

    result = say("what are the facts?", host=LLMHost(gateway=ScriptedGateway([from_memory])))

    assert tools_called(result) == ["get_facts"]
    assert result.display["resource_uri"] == "ui://greeo/facts"
    assert "From what I recall" not in result.spoken
    assert result.spoken.startswith("SYNTHETIC. Residents of Veloria")


def test_llm_host_small_talk_keeps_the_models_reply_and_searches_nothing() -> None:
    result = say("thanks a lot", host=LLMHost(gateway=ScriptedGateway([says("You're welcome.")])))

    assert tools_called(result) == []
    assert result.spoken == "You're welcome."


def test_model_reasoning_is_never_spoken() -> None:
    """Seen live with Nova Lite: a <thinking> block arrived ahead of the reply."""
    closed = {
        "output": {
            "message": {
                "role": "assistant",
                "content": [{"text": "<thinking>The user said thanks.</thinking>You're welcome."}],
            }
        }
    }
    cut_off = {"output": {"message": {"role": "assistant", "content": [
        {"text": "Glad to help. <thinking>The user said thanks, so I will"}]}}}  # fmt: skip

    assert parse_tool_turn(closed).text == "You're welcome."
    assert parse_tool_turn(cut_off).text == "Glad to help."


def test_llm_host_keeps_only_plain_text_history(story: Story, simulator: SessionStore) -> None:
    gateway = ScriptedGateway([wants("get_facts", story_id=story.pk), says("done")])

    say("what happened?", host=LLMHost(gateway=gateway))

    roles = [message["role"] for message in simulator.load("s1").messages]
    assert roles == ["user", "assistant"]
    assert "toolResult" not in str(simulator.load("s1").messages)


def test_model_failure_is_a_friendly_reply() -> None:
    class Failing:
        def generate_with_tools(self, *args, **kwargs):
            raise LLMProviderError("synthetic provider outage")

    result = say("hello", host=LLMHost(gateway=Failing()))

    assert result.spoken == THINKING_TROUBLE and result.host_mode == "llm"


def test_host_mode_follows_the_llm_backend_setting() -> None:
    with override_settings(LLM_BACKEND="mock"):
        assert isinstance(configured_host(), MockHost)
    with override_settings(LLM_BACKEND="bedrock"):
        assert configured_host().mode == "llm"


# The gateway extension -----------------------------------------------------------------


class ConverseClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] = {}

    def converse(self, **request: Any) -> dict[str, Any]:
        self.request = request
        return {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Let me find that."},
                        {
                            "toolUse": {
                                "toolUseId": "t1",
                                "name": "get_facts",
                                "input": {"story_id": "st_x"},
                            }
                        },
                    ],
                }
            },
            "usage": {"inputTokens": 11, "outputTokens": 7},
        }


class NoBudget:
    def __init__(self) -> None:
        self.settled: list[tuple[int, int]] = []

    def reserve(self, run_id: str, prompt: str, max_tokens: int) -> int:
        return 100

    def settle(self, reservation: int, actual_tokens: int) -> None:
        self.settled.append((reservation, actual_tokens))


@override_settings(BEDROCK_MODEL_ID="test.model", AWS_REGION="us-east-1")
def test_gateway_tool_turn_uses_converse_tool_config_and_is_audited() -> None:
    client, budget = ConverseClient(), NoBudget()
    gateway = LLMGateway(backend=BedrockLLM(client=client), budget=budget)
    tools = [{"name": "get_facts", "description": "Facts.", "input_schema": {"type": "object"}}]
    messages = [{"role": "user", "content": [{"text": "what happened?"}]}]

    turn = gateway.generate_with_tools("simulator_host", messages, tools)

    assert turn.text == "Let me find that."
    assert turn.tool_calls == (ToolCall(id="t1", name="get_facts", arguments={"story_id": "st_x"}),)
    spec = client.request["toolConfig"]["tools"][0]["toolSpec"]
    assert (spec["name"], spec["inputSchema"]) == ("get_facts", {"json": {"type": "object"}})
    system_prompt = " ".join(client.request["system"][0]["text"].split())
    assert "delivered to the listener exactly as written" in system_prompt
    call = LLMCall.objects.get()
    assert (call.prompt_name, call.ok, call.tokens_in, call.tokens_out) == (
        "simulator_host",
        True,
        11,
        7,
    )
    assert budget.settled == [(100, 18)]


# The HTTP API ----------------------------------------------------------------------------


@pytest.fixture
def api() -> APIClient:
    return APIClient(headers=USER)


def post_turn(api: APIClient, session: str, text: str):
    return api.post("/api/simulator/turn", {"session_id": session, "text": text}, format="json")


def test_turn_endpoint_returns_spoken_display_trace_and_mode(story: Story, api: APIClient) -> None:
    response = api.post(
        "/api/simulator/turn",
        {"session_id": "web-1", "text": "tell me about the footbridge"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"spoken", "display", "tool_trace", "host_mode"}
    assert body["host_mode"] == "mock"
    assert body["display"]["resource_uri"] == "ui://greeo/tale"
    assert [step["tool"] for step in body["tool_trace"]] == ["search_events", "tell_tale"]
    assert set(body["tool_trace"][0]) == {"tool", "args", "ms", "ok"}


def test_turn_endpoint_validates_input(api: APIClient) -> None:
    missing = api.post("/api/simulator/turn", {"session_id": "web-1"}, format="json")
    bad_id = api.post("/api/simulator/turn", {"session_id": "bad id!", "text": "hi"}, format="json")

    assert missing.status_code == 400 and bad_id.status_code == 400


def test_resource_proxy_serves_only_greeo_cards(api: APIClient) -> None:
    card = api.get("/api/simulator/resource", {"uri": "ui://greeo/tale"})
    other = api.get("/api/simulator/resource", {"uri": "ui://elsewhere/card"})
    web = api.get("/api/simulator/resource", {"uri": "https://example.com/"})
    missing = api.get("/api/simulator/resource", {"uri": "ui://greeo/nothing"})

    assert card.status_code == 200
    assert card.json()["mime_type"] == "text/html;profile=mcp-app"
    assert card.json()["text"].startswith("<!doctype html>")
    assert (other.status_code, web.status_code, missing.status_code) == (400, 400, 404)


def test_reset_endpoint_clears_the_session(
    story: Story, api: APIClient, simulator: SessionStore
) -> None:
    api.post(
        "/api/simulator/turn",
        {"session_id": "web-2", "text": "tell me about the footbridge"},
        format="json",
    )
    assert simulator.load("web-2").last_story_id == story.pk

    response = api.post("/api/simulator/reset", {"session_id": "web-2"}, format="json")
    after = post_turn(api, "web-2", "go on")

    assert response.json() == {"reset": True}
    assert simulator.load("web-2").last_story_id is None
    assert after.json()["spoken"].startswith("Which story would you like?")


def test_tts_endpoint_returns_204_without_a_speech_backend(api: APIClient) -> None:
    response = api.post("/api/simulator/tts", {"text": "Listen."}, format="json")

    assert response.status_code == 204


def test_tts_endpoint_returns_audio_when_available(api: APIClient, monkeypatch) -> None:
    audio = speech.SpeechAudio(audio=b"SYNTHETIC-MP3", content_type="audio/mpeg", cached=True)
    monkeypatch.setattr(speech, "synthesize_sentence", lambda text, voice=None: audio)

    response = api.post(
        "/api/simulator/tts", {"text": "Listen.", "voice": "village_fire"}, format="json"
    )

    assert response.status_code == 200
    assert response["Content-Type"] == "audio/mpeg"
    assert response["X-Greeo-Speech-Cache"] == "hit"
    assert response.content == b"SYNTHETIC-MP3"


def test_guests_are_used_when_dev_identity_is_off(story: Story, api: APIClient, settings) -> None:
    settings.MCP_ALLOW_DEV_IDENTITY = False

    api.post(
        "/api/simulator/turn",
        {"session_id": "web-3", "text": "tell me about the footbridge"},
        format="json",
    )

    assert not StoryEncounter.objects.exists()


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:4200"])
def test_cors_allows_listed_origins_only(api: APIClient) -> None:
    allowed = api.options(
        "/api/simulator/turn",
        HTTP_ORIGIN="http://localhost:4200",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
    )
    blocked = api.options(
        "/api/simulator/turn",
        HTTP_ORIGIN="https://evil.example",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
    )
    outside = api.get("/healthz", HTTP_ORIGIN="http://localhost:4200")

    assert allowed["Access-Control-Allow-Origin"] == "http://localhost:4200"
    assert "Access-Control-Allow-Origin" not in blocked
    assert "Access-Control-Allow-Origin" not in outside  # CORS covers the simulator API only
