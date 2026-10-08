"""LLMHost: a model chooses which MCP tools to call, as Alexa+ does.

The model decides the tools; it does not write the words a listener hears when a tool
answered. Those come from the tool's `spoken` text, unchanged (see host.py).

Models sometimes answer a story question from earlier turns, or invent stories, instead
of calling a tool, which would put unchecked words in Greeo's voice. When the model calls
no tool, the keyword router gets a say: if it recognises a Greeo request, its tools
answer instead. Otherwise the model's own words are allowed only as brief small talk;
anything about stories or the news is replaced by a real search for what was asked.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings

from apps.llm.client import LLMGateway

from .mcp_link import McpLink, ToolOutcome
from .mock_host import MockHost
from .state import SessionState

logger = logging.getLogger(__name__)
PROMPT_NAME = "simulator_host"
# A model's own words, without a tool, may only be brief small talk.
SMALL_TALK_WORDS = 25
NEWS_TALK = re.compile(
    r"\b(stor(?:y|ies)|news|headlines?|report(?:ed|s)?|according to|here are|happened|"
    r"proverbs?|facts?)\b",
    re.IGNORECASE,
)


class LLMHost:
    mode = "llm"

    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway or LLMGateway()

    async def run(
        self, link: McpLink, text: str, state: SessionState
    ) -> tuple[list[ToolOutcome], str | None]:
        """Loop model -> tools -> model, at most SIMULATOR_MAX_TOOL_ITERATIONS times."""
        tools = await link.tools()
        messages: list[dict[str, Any]] = [
            *state.messages,
            {"role": "user", "content": [{"text": text + state.context_note()}]},
        ]
        outcomes: list[ToolOutcome] = []
        ask_model = sync_to_async(self.gateway.generate_with_tools, thread_sensitive=True)
        for _ in range(settings.SIMULATOR_MAX_TOOL_ITERATIONS):
            turn = await ask_model(PROMPT_NAME, messages, tools)
            messages.append(turn.assistant_message)
            if not turn.tool_calls:
                if outcomes:
                    return outcomes, turn.text
                return await self._safety_net(link, text, state, turn.text)
            results = []
            for request in turn.tool_calls:
                outcome = await link.call(request.name, request.arguments)
                if any(outcome is earlier for earlier in outcomes):
                    # The model asked again for a beat this turn already told: the turn is done.
                    return outcomes, None
                outcomes.append(outcome)
                results.append(
                    {
                        "toolResult": {
                            "toolUseId": request.id,
                            "content": [{"json": outcome.structured or {"spoken": outcome.spoken}}],
                            "status": "success" if outcome.ok else "error",
                        }
                    }
                )
            messages.append({"role": "user", "content": results})
        # The cap was reached while the model still wanted tools: stop and use what we have.
        return outcomes, None

    async def _safety_net(
        self, link: McpLink, text: str, state: SessionState, reply: str
    ) -> tuple[list[ToolOutcome], str | None]:
        return await keyword_safety_net(link, text, state, reply)


async def keyword_safety_net(
    link: McpLink, text: str, state: SessionState, reply: str
) -> tuple[list[ToolOutcome], str | None]:
    """The model called no tool: let the keyword router answer if it recognises the request.

    Shared by every model-driven host, so none of them can put unchecked words in Greeo's
    voice when a tool should have answered.
    """
    outcomes, _ = await MockHost().run(link, text, state, search=False)
    if not outcomes and may_speak_own_words(reply):
        return [], reply
    if not outcomes:
        # Seen live with Nova Lite: a list of made-up stories, no tool called. Search what
        # the listener actually asked; the real stories, or an honest "not found", answer.
        logger.warning("Simulator model talked about the news without a tool; searching.")
        outcomes, _ = await MockHost().run(link, text, state, search=True)
    logger.info(
        "Simulator model answered without tools; keyword router called %s.",
        ", ".join(outcome.tool for outcome in outcomes),
    )
    return outcomes, None


def may_speak_own_words(reply: str) -> bool:
    """Brief small talk only ("You're welcome."): never stories, facts or the news."""
    return bool(reply) and len(reply.split()) <= SMALL_TALK_WORDS and not NEWS_TALK.search(reply)
