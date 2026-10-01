"""One simulator turn: connect to MCP, let a host choose tools, build the reply.

The reply's words come from the last tool's `spoken` text, exactly as returned. That is
enforced here in code, for both hosts, so the storyteller's wording and the verified
proverbs cannot be reworded on the way out. Real Alexa+ composes its own phrasing from
tool data and we cannot control that; see docs/notes/reading.md.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from asgiref.sync import async_to_sync
from django.conf import settings

from apps.core.models import StageTrace
from apps.core.speech import forbidden_words
from apps.llm.exceptions import LLMError
from apps.mcp_server.voice import truncate_spoken

from .llm_host import LLMHost
from .mcp_link import (
    CARD_PREFIX,
    Connector,
    Credentials,
    McpLink,
    ToolOutcome,
    connect,
    http_status,
)
from .mock_host import MockHost
from .state import SessionState, SessionStore

logger = logging.getLogger(__name__)

UNREACHABLE = "I can't reach Greeo right now. Please try again in a moment."
THINKING_TROUBLE = "I'm having trouble with that just now. You can ask for today's stories."
SIGN_IN_AGAIN = "That sign-in is no longer valid. Please sign in again to use your saved stories."
SLOW_DOWN = "That's a lot at once. Give me a moment, then ask again."
NOTHING_SAID = "I didn't catch that. You can ask for today's stories, or name a topic."


class ModelTrouble(Exception):
    """The model behind the LLM host failed; the listener gets a plain apology."""


def _find(error: BaseException, kind: type[BaseException]) -> BaseException | None:
    """Look for an exception of this kind, including inside exception groups."""
    if isinstance(error, kind):
        return error
    for inner in getattr(error, "exceptions", ()):
        found = _find(inner, kind)
        if found is not None:
            return found
    return None


def _probe(credentials: Credentials) -> int | None:
    """Ask MCP how it answers these credentials; never raises."""
    try:
        return async_to_sync(http_status)(credentials)
    except Exception:
        return None


class Host(Protocol):
    mode: str

    async def run(
        self, link: McpLink, text: str, state: SessionState
    ) -> tuple[list[ToolOutcome], str | None]: ...


@dataclass(frozen=True)
class TurnResult:
    spoken: str
    host_mode: str
    display: dict[str, Any] = field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "spoken": self.spoken,
            "display": self.display,
            "tool_trace": self.tool_trace,
            "host_mode": self.host_mode,
        }


def configured_host() -> Host:
    """Mock backend means the scripted router; anything else means a model chooses tools."""
    return MockHost() if settings.LLM_BACKEND == "mock" else LLMHost()


def run_turn(
    session_id: str,
    text: str,
    credentials: Credentials,
    *,
    host: Host | None = None,
    connector: Connector | None = None,
    store: SessionStore | None = None,
) -> TurnResult:
    """Handle one thing the listener said and return what to speak and show."""
    host = host or configured_host()
    store = store or SessionStore()
    started = time.monotonic()
    state = store.load(session_id)
    try:
        outcomes, reply = async_to_sync(_converse)(
            host, connector or connect, credentials, text, state
        )
        failure = ""
    except Exception as error:  # Model trouble, MCP unreachable: never a stack trace.
        trouble = _find(error, ModelTrouble)
        status = None if trouble else _probe(credentials)
        if status == 401:
            # MCP rejected the caller's token: say so, instead of blaming the connection.
            logger.info("Simulator credentials were rejected by MCP.")
            outcomes, reply, failure = [], SIGN_IN_AGAIN, "credentials rejected (401)"
        elif status == 429:
            outcomes, reply, failure = [], SLOW_DOWN, "rate limited (429)"
        elif trouble is not None:
            logger.warning("Simulator model call failed: %s", trouble)
            outcomes, reply, failure = [], THINKING_TROUBLE, str(trouble)
        else:
            logger.exception("Simulator could not complete the turn")
            outcomes, reply, failure = [], UNREACHABLE, str(error)

    spoken = _spoken(outcomes, reply)
    _remember(state, outcomes, text, spoken)
    store.save(session_id, state)
    result = TurnResult(
        spoken=spoken,
        host_mode=host.mode,
        display=_display(outcomes),
        tool_trace=[outcome.trace() for outcome in outcomes],
    )
    _trace(host.mode, text, result, started, failure)
    return result


async def _converse(
    host: Host, connector: Connector, credentials: Credentials, text: str, state: SessionState
) -> tuple[list[ToolOutcome], str | None]:
    async with connector(credentials) as link:
        try:
            return await host.run(link, text, state)
        except LLMError as error:
            # Caught here: outside the connection it would arrive wrapped in a task group.
            raise ModelTrouble(str(error)) from None


def _spoken(outcomes: list[ToolOutcome], reply: str | None) -> str:
    """A tool's spoken text is used unchanged; only the host's own words are tidied."""
    if outcomes and outcomes[-1].spoken:
        return outcomes[-1].spoken
    own = truncate_spoken(reply or "")
    return own if own and not forbidden_words(own) else NOTHING_SAID


def _display(outcomes: list[ToolOutcome]) -> dict[str, Any]:
    """What the screen shows: the last result, and its card when the tool has one."""
    if not outcomes:
        return {}
    last = outcomes[-1]
    return {
        "tool": last.tool,
        "resource_uri": last.resource_uri,
        "structured": last.structured,
        "is_error": not last.ok,
    }


def _remember(state: SessionState, outcomes: list[ToolOutcome], said: str, spoken: str) -> None:
    """Update the host's short-term context from what the tools returned."""
    for outcome in outcomes:
        if not outcome.ok:
            continue
        if outcome.tool == "set_preferences" and outcome.structured.get("reset"):
            state.last_story_id, state.last_stories, state.last_listing = None, [], None
            state.messages = []
        if outcome.structured.get("story_id"):
            state.last_story_id = outcome.structured["story_id"]
        if "stories" in outcome.structured and outcome.tool != "get_saved_stories":
            state.last_stories = [
                {"story_id": item["story_id"], "title": item["title"]}
                for item in outcome.structured["stories"]
            ]
            state.last_listing = {
                "tool": outcome.tool,
                "args": {k: v for k, v in outcome.args.items() if k != "page"},
                "page": outcome.structured.get("page", 1),
            }
        if outcome.tool == "get_saved_stories":
            state.last_stories = [
                {"story_id": item["story_id"], "title": item["title"]}
                for item in outcome.structured.get("stories", [])
            ]
    state.remember_exchange(said, spoken)


def _trace(mode: str, text: str, result: TurnResult, started: float, failure: str) -> None:
    """Audit the turn, recording whether a script or a model chose the tools."""
    StageTrace.objects.create(
        stage="simulator_turn",
        status=StageTrace.Status.FAILED if failure else StageTrace.Status.OK,
        host_mode=mode,
        duration_ms=round((time.monotonic() - started) * 1000),
        input_summary=text[:200],
        output_summary=", ".join(item["tool"] for item in result.tool_trace)[:500],
        error=failure[:2000],
    )


def reset_session(
    session_id: str,
    credentials: Credentials,
    *,
    connector: Connector | None = None,
    store: SessionStore | None = None,
) -> None:
    """Forget this conversation, here and in Greeo's own session context."""
    (store or SessionStore()).clear(session_id)
    if credentials:
        try:
            async_to_sync(_reset_remote)(connector or connect, credentials)
        except Exception:
            logger.warning("Could not reset Greeo session context.", exc_info=True)


async def _reset_remote(connector: Connector, credentials: Credentials) -> None:
    async with connector(credentials) as link:
        await link.call("set_preferences", {"reset": True})


def read_card(
    uri: str, credentials: Credentials | None = None, *, connector: Connector | None = None
) -> tuple[str, str]:
    """resources/read through MCP for one of Greeo's cards."""
    if not uri.startswith(CARD_PREFIX):
        raise ValueError("Only Greeo card resources can be read.")
    return async_to_sync(_read_card)(connector or connect, credentials or {}, uri)


async def _read_card(connector: Connector, credentials: Credentials, uri: str) -> tuple[str, str]:
    async with connector(credentials) as link:
        return await link.read_card(uri)
