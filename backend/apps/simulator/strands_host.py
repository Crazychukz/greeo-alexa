"""StrandsHost: a Strands Agents agent chooses which MCP tools to call, as Alexa+ does.

The same contract as LLMHost, with the Strands Agents SDK running the agent loop
(model -> tools -> model) instead of our own:

- Tools come from the MCP server's tools/list and are called through ContextLink, so
  the conversation's story is filled in and a guest never skips a beat.
- Tools run one at a time (ContextLink keeps per-turn state), at most
  SIMULATOR_MAX_TOOL_ITERATIONS per turn, and a repeated beat ends the turn.
- The model chooses tools; the words a listener hears come from the tool's `spoken`
  text, unchanged (host.py). If the model calls no tool, the keyword router may answer.
- Strands calls Bedrock itself, but every run is budgeted and audited by the gateway.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from strands import Agent
from strands.models import BedrockModel
from strands.models.model import Model
from strands.tools.executors import SequentialToolExecutor
from strands.tools.tools import PythonAgentTool
from strands.types.exceptions import MaxTokensReachedException

from apps.llm.backends import without_reasoning
from apps.llm.client import LLMGateway, model_for_prompt
from apps.llm.exceptions import LLMProviderError
from apps.llm.prompt_registry import load_prompt

from .llm_host import keyword_safety_net
from .mcp_link import McpLink, ToolOutcome
from .state import SessionState

logger = logging.getLogger(__name__)
PROMPT_NAME = "simulator_host"


class StrandsHost:
    mode = "strands"

    def __init__(self, model: Model | None = None, gateway: LLMGateway | None = None) -> None:
        self._model = model
        self.gateway = gateway or LLMGateway()

    def model(self) -> Model:
        """Bedrock through Strands, with the host's own model, region and output cap."""
        if self._model is None:
            self._model = BedrockModel(
                model_id=model_for_prompt(PROMPT_NAME),
                region_name=settings.AWS_REGION,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=0.0,
                streaming=False,
            )
        return self._model

    async def run(
        self, link: McpLink, text: str, state: SessionState
    ) -> tuple[list[ToolOutcome], str | None]:
        outcomes: list[ToolOutcome] = []
        tools = [_as_strands_tool(link, spec, outcomes) for spec in await link.tools()]
        agent = Agent(
            model=self.model(),
            system_prompt=load_prompt(PROMPT_NAME).text,
            messages=[*state.messages],
            tools=tools,
            tool_executor=SequentialToolExecutor(),
            callback_handler=None,  # nothing printed; the turn's trace is the record
        )
        reply, usage, error = await self._invoke(agent, text + state.context_note(), state)
        if error is not None:
            # As an LLMError, host.py answers with its friendly "trouble thinking" reply.
            raise LLMProviderError(f"Strands agent failed: {error}") from error
        if outcomes:
            return outcomes, reply
        logger.debug("Strands agent used %s tokens and called no tool.", usage)
        return await keyword_safety_net(link, text, state, reply)

    async def _invoke(
        self, agent: Agent, text: str, state: SessionState
    ) -> tuple[str, dict[str, int], Exception | None]:
        """Run the agent once, inside a budget reservation and one audit record."""
        reserve = sync_to_async(self.gateway.reserve_agent_run, thread_sensitive=True)
        settle = sync_to_async(self.gateway.settle_agent_run, thread_sensitive=True)
        reservation = await reserve(
            PROMPT_NAME,
            [*state.messages, {"role": "user", "content": [{"text": text}]}],
            settings.SIMULATOR_MAX_TOOL_ITERATIONS + 1,
        )
        started = time.monotonic()
        usage = {"inputTokens": 0, "outputTokens": 0}
        try:
            result = await agent.invoke_async(text)
        except MaxTokensReachedException as error:
            # Seen live: the model began writing a tale itself and hit the output cap.
            # Treated as "no tool called", so the safety net answers with Greeo's tools.
            await settle(
                reservation,
                prompt_name=PROMPT_NAME,
                model_id=self._model_id(),
                backend_name="strands",
                tokens_in=0,
                tokens_out=settings.LLM_MAX_TOKENS,
                latency_ms=round((time.monotonic() - started) * 1000),
                ok=False,
                error=f"output cap reached: {error}",
            )
            return "", usage, None
        except Exception as error:  # reported after the reservation is settled
            await settle(
                reservation,
                prompt_name=PROMPT_NAME,
                model_id=self._model_id(),
                backend_name="strands",
                tokens_in=0,
                tokens_out=0,
                latency_ms=round((time.monotonic() - started) * 1000),
                ok=False,
                error=str(error),
            )
            return "", usage, error
        usage = dict(result.metrics.accumulated_usage)
        await settle(
            reservation,
            prompt_name=PROMPT_NAME,
            model_id=self._model_id(),
            backend_name="strands",
            tokens_in=int(usage.get("inputTokens", 0)),
            tokens_out=int(usage.get("outputTokens", 0)),
            latency_ms=round((time.monotonic() - started) * 1000),
            ok=True,
        )
        return reply_text(result.message), usage, None

    def _model_id(self) -> str:
        config = self.model().get_config()
        return str(config.get("model_id", "")) if isinstance(config, dict) else ""


def _as_strands_tool(
    link: McpLink, spec: dict[str, Any], outcomes: list[ToolOutcome]
) -> PythonAgentTool:
    """One MCP tool as a Strands tool that calls the MCP server through ContextLink."""
    name = spec["name"]

    async def call(tool_use: dict[str, Any], **invocation_state: Any) -> dict[str, Any]:
        outcome = await link.call(name, dict(tool_use.get("input") or {}))
        repeated = any(outcome is earlier for earlier in outcomes)
        if not repeated:
            outcomes.append(outcome)
        if repeated or len(outcomes) >= settings.SIMULATOR_MAX_TOOL_ITERATIONS:
            # A beat this turn already told, or the cap: the turn is done.
            invocation_state.setdefault("request_state", {})["stop_event_loop"] = True
        return {
            "toolUseId": tool_use["toolUseId"],
            "status": "success" if outcome.ok else "error",
            "content": [{"json": outcome.structured or {"spoken": outcome.spoken}}],
        }

    tool_spec = {
        "name": name,
        "description": spec["description"],
        "inputSchema": {"json": spec["input_schema"]},
    }
    return PythonAgentTool(name, tool_spec, call)


def reply_text(message: dict[str, Any] | None) -> str:
    """The agent's own closing words, if any, without inline reasoning."""
    blocks = (message or {}).get("content", [])
    text = " ".join(block["text"] for block in blocks if isinstance(block.get("text"), str))
    return without_reasoning(text)
