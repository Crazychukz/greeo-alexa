"""The Strands host: a real Strands Agents agent, a scripted model, the real MCP server."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from apps.simulator import host as host_module
from apps.simulator.host import THINKING_TROUBLE, configured_host
from apps.simulator.llm_host import LLMHost
from apps.simulator.mock_host import MockHost
from apps.simulator.strands_host import StrandsHost, reply_text
from apps.stories.models import Story
from strands.models.model import Model

# simulator: the in-process MCP server and in-memory sessions (autouse, so imported here).
from tests.test_simulator import say, simulator, tools_called  # noqa: F401

pytestmark = pytest.mark.django_db


class ScriptedModel(Model):
    """A Strands model that plays prepared turns and records what the agent sent it.

    A turn is ("tool", name, arguments), ("text", words) or an exception to raise.
    """

    def __init__(self, turns: list[Any]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    def update_config(self, **model_config: Any) -> None:
        pass

    def get_config(self) -> dict[str, Any]:
        return {"model_id": "scripted-model"}

    async def structured_output(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def stream(
        self, messages: Any, tool_specs: Any = None, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncIterator[dict[str, Any]]:
        self.requests.append(
            {"messages": list(messages), "tools": tool_specs or [], "system": system_prompt}
        )
        turn = self.turns.pop(0) if len(self.turns) > 1 else self.turns[0]
        if isinstance(turn, Exception):
            raise turn
        yield {"messageStart": {"role": "assistant"}}
        if turn[0] == "tool":
            _, name, arguments = turn
            use = {"toolUseId": f"use-{name}-{len(self.requests)}", "name": name}
            yield {"contentBlockStart": {"start": {"toolUse": use}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(arguments)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn[1]}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        usage = {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120}
        yield {"metadata": {"usage": usage, "metrics": {"latencyMs": 1}}}


class RecordingGateway:
    """Stands in for the LLM gateway's agent-run budget and audit."""

    def __init__(self) -> None:
        self.reserved: list[int] = []
        self.settled: list[dict[str, Any]] = []

    def reserve_agent_run(self, prompt_name: str, messages: list[Any], max_calls: int) -> int:
        self.reserved.append(max_calls)
        return len(self.reserved)

    def settle_agent_run(self, reservation: int, **record: Any) -> None:
        self.settled.append({"reservation": reservation, **record})


def strands_host(*turns: Any) -> tuple[StrandsHost, ScriptedModel, RecordingGateway]:
    model, gateway = ScriptedModel(list(turns)), RecordingGateway()
    return StrandsHost(model=model, gateway=gateway), model, gateway


def test_a_strands_agent_tells_the_tale_through_mcp_in_greeo_s_own_words(story: Story) -> None:
    host, model, gateway = strands_host(
        ("tool", "tell_tale", {"story_id": story.pk, "beat": 1}),
        ("text", "Here is my own summary instead."),
    )

    result = say("tell me the story", host=host)

    assert result.host_mode == "strands"
    assert tools_called(result) == ["tell_tale"]
    assert result.spoken == result.display["structured"]["text"]  # the tool's words, unchanged
    assert "my own summary" not in result.spoken
    first = model.requests[0]
    assert "Greeo" in first["system"]  # the registered simulator_host prompt
    assert {spec["name"] for spec in first["tools"]} >= {"tell_tale", "get_facts", "get_help"}
    fed_back = model.requests[1]["messages"][-1]["content"][0]["toolResult"]
    assert fed_back["status"] == "success" and fed_back["content"][0]["json"]["beat"] == 1


def test_every_strands_run_is_budgeted_and_audited(story: Story, settings) -> None:
    host, _, gateway = strands_host(("tool", "get_help", {}), ("text", "Done."))

    say("what can you do?", host=host)

    assert gateway.reserved == [settings.SIMULATOR_MAX_TOOL_ITERATIONS + 1]
    (record,) = gateway.settled
    assert record["backend_name"] == "strands" and record["ok"] is True
    assert record["model_id"] == "scripted-model"
    assert (record["tokens_in"], record["tokens_out"]) == (200, 40)  # two model calls


def test_a_guest_continuing_never_skips_a_beat(story: Story) -> None:
    host, _, _ = strands_host(
        ("tool", "tell_tale", {"story_id": story.pk, "beat": 1}), ("text", ".")
    )
    say("tell me the story", session="g1", host=host)
    skipper, _, _ = strands_host(("tool", "tell_tale", {"beat": 3}), ("text", "."))

    result = host_module.run_turn("g1", "continue", {}, host=skipper)

    assert result.display["structured"]["beat"] == 2  # ContextLink clamps the guest's beat


def test_a_repeated_beat_ends_the_turn(story: Story) -> None:
    host, model, _ = strands_host(("tool", "tell_tale", {"story_id": story.pk, "beat": 1}))

    result = say("tell me the story", host=host)

    assert tools_called(result) == ["tell_tale"]
    assert len(model.requests) == 2  # asked again for the same beat, then stopped


def test_when_the_agent_calls_no_tool_the_keyword_router_answers(story: Story) -> None:
    host, _, _ = strands_host(("text", "I think the bridge story is lovely."))
    say("tell me about the footbridge", host=MockHost())  # a story in context

    result = say("what are the facts?", host=host)

    assert tools_called(result) == ["get_facts"]
    assert "lovely" not in result.spoken


def test_a_model_failure_is_a_friendly_reply_and_still_audited(story: Story) -> None:
    host, _, gateway = strands_host(RuntimeError("throttled"))

    result = say("what's new?", host=host)

    assert result.spoken == THINKING_TROUBLE
    assert gateway.settled[0]["ok"] is False and "throttled" in gateway.settled[0]["error"]


def test_the_host_follows_the_setting(settings) -> None:
    settings.SIMULATOR_HOST = "strands"
    assert isinstance(configured_host(), StrandsHost)
    settings.SIMULATOR_HOST = "llm"
    assert isinstance(configured_host(), LLMHost)
    settings.SIMULATOR_HOST, settings.LLM_BACKEND = "", "mock"
    assert isinstance(configured_host(), MockHost)


def test_reasoning_is_stripped_from_the_agent_s_own_words() -> None:
    message = {"content": [{"text": "<thinking>pick a tool</thinking>Here you go."}]}
    assert reply_text(message) == "Here you go."
    assert reply_text(None) == ""


def test_a_strands_agent_inventing_stories_is_replaced_by_a_real_search(story: Story) -> None:
    host, _, _ = strands_host(
        ("text", "Here are stories about Messi: Messi's return to Barcelona.")
    )

    result = say("tell me about Messi", host=host)

    assert tools_called(result) == ["search_events"] and "Barcelona" not in result.spoken


def test_hitting_the_output_cap_falls_back_to_greeo_s_tools(story: Story) -> None:
    """Seen live: on "continue" the model began writing the tale itself and hit the cap."""
    from strands.types.exceptions import MaxTokensReachedException

    first = say("tell me about the footbridge", host=MockHost())  # one match: beat 1
    host, _, gateway = strands_host(MaxTokensReachedException("cap"))

    result = say("continue", host=host)

    assert tools_called(result) == ["tell_tale"]
    assert result.display["structured"]["beat"] == first.display["structured"]["beat"] + 1
    assert gateway.settled[0]["ok"] is False
