"""MockHost: a keyword router so the demo runs offline and the same way every time.

This is scripted behaviour, not model reasoning, and every reply it produces is labelled
host_mode "mock". It still discovers and calls the real MCP tools; only the choice of
tool is scripted.
"""

from __future__ import annotations

import re

from .mcp_link import McpLink, ToolOutcome
from .state import SessionState

HELP_TEXT = (
    "I tell today's news as short tales, with a proverb where one fits. Ask for today's "
    "stories or name a topic, then ask for the facts, the background or the sources."
)
TONE_WORDS = {
    "serious": "serious",
    "lighter": "light",
    "light": "light",
    "playful": "light",
    "balanced": "balanced",
}
SEARCH_LEADS = (
    "tell me about",
    "tell me a story about",
    "a story about",
    "stories about",
    "any news about",
    "any news on",
    "what about",
    "search for",
    "find",
    "news about",
)
ORDINALS = {"first": 0, "1": 0, "one": 0, "second": 1, "2": 1, "two": 1, "third": 2, "3": 2}


def normalise(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", text.lower().replace("’", "'")).split())


def has(said: str, *phrases: str) -> bool:
    return any(phrase in said for phrase in phrases)


def tone_in(said: str) -> str | None:
    """A tone change needs a change phrase, so a topic like 'light rail' is still a search."""
    if not has(said, "make it", "tone", "telling", "lighter", "more serious", "less serious"):
        return None
    return next((tone for word, tone in TONE_WORDS.items() if word in said.split()), None)


def pick_listed_story(said: str, stories: list[dict[str, str]]) -> str | None:
    """Resolve 'the first one' or part of a title against the stories just listed."""
    for word in said.split():
        if word in ORDINALS and ORDINALS[word] < len(stories):
            return stories[ORDINALS[word]]["story_id"]
    wanted = said.removeprefix("the ").strip()
    if len(wanted) >= 4:
        for story in stories:
            if wanted in normalise(story["title"]):
                return story["story_id"]
    return None


def search_query(said: str) -> str:
    for lead in SEARCH_LEADS:
        if said.startswith(lead + " "):
            return said[len(lead) :].strip()
    return said


class MockHost:
    mode = "mock"

    async def run(
        self, link: McpLink, text: str, state: SessionState, *, search: bool = True
    ) -> tuple[list[ToolOutcome], str | None]:
        """Return the tool calls made and, when no tool was called, the host's own reply.

        With `search` off, anything the keywords do not recognise calls no tool, so the
        LLM host can use this router as a safety net without searching on "thanks".
        """
        said = normalise(text)
        story = state.last_story_id
        outcomes: list[ToolOutcome] = []

        async def call(tool: str, **arguments: object) -> ToolOutcome:
            outcomes.append(await link.call(tool, dict(arguments)))
            return outcomes[-1]

        tone = tone_in(said)
        if has(said, "start over", "start fresh", "begin again", "reset"):
            await call("set_preferences", reset=True)
        elif tone:
            await call("set_preferences", tone=tone)
            if story:
                await call("tell_tale", story_id=story, beat=1, tone=tone)
        elif has(said, "save"):
            await call("save_for_later", story_id=story)
        elif has(said, "what was i listening", "saved stor", "my stories", "where did i stop"):
            await call("get_saved_stories")
        elif has(said, "what can you do", "help"):
            return outcomes, HELP_TEXT
        elif has(said, "go on", "continue", "what happened next", "keep going", "carry on"):
            await call("tell_tale", story_id=story)
        elif has(said, "from the beginning", "start the tale", "tell it again"):
            await call("tell_tale", story_id=story, beat=1)
        elif story and has(said, "tell me the story", "tell the tale", "hear the tale"):
            await call("tell_tale", story_id=story)
        elif has(said, "lesson", "moral", "reflection", "the point"):
            await call("get_moral", story_id=story)
        elif has(said, "proverb", "saying"):
            await call("explain_proverb", story_id=story)
        elif has(
            said, "actually happened", "really happened", "facts", "is it true", "is that true"
        ):
            await call("get_facts", story_id=story)
        elif has(said, "why does it matter", "why it matters", "background", "context"):
            await call("get_context", story_id=story)
        elif has(said, "sides", "perspectives", "views", "what do people think", "opinions"):
            await call("get_perspectives", story_id=story)
        elif has(said, "evidence", "sources", "who reported", "where did this come from"):
            await call("get_sources", story_id=story)
        elif has(said, "more stories", "more results", "next page") and state.last_listing:
            listing = state.last_listing
            await call(listing["tool"], **{**listing["args"], "page": listing["page"] + 1})
        elif has(said, "what's going on", "whats going on", "what's new", "todays stories",
                 "today's stories", "briefing", "the news", "latest"):  # fmt: skip
            await call("get_briefing")
        elif picked := pick_listed_story(said, state.last_stories):
            await call("tell_tale", story_id=picked, beat=1)
        elif search:
            found = await call("search_events", query=search_query(said))
            listed = found.structured.get("stories", [])
            if found.ok and len(listed) == 1:
                await call("tell_tale", story_id=listed[0]["story_id"], beat=1)
        return outcomes, None
