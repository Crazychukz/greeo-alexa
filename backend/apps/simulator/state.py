"""Conversation state for one simulator session, kept in Redis for 30 minutes.

This is the host's own short-term memory (what it just listed, which story is current),
like the conversation context Alexa+ keeps. Listener memory that must survive sessions
lives in Greeo, behind the MCP tools.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Protocol

import redis
from django.conf import settings

logger = logging.getLogger(__name__)
MAX_HISTORY_MESSAGES = 12


@dataclass
class SessionState:
    last_story_id: str | None = None
    # Stories most recently listed, so "the first one" or a title can be resolved.
    last_stories: list[dict[str, str]] = field(default_factory=list)
    # The listing call behind them, so "more stories" can ask for the next page.
    last_listing: dict[str, Any] | None = None
    # The beat a bare "continue" should play next, for listeners Greeo cannot remember
    # (guests): Alexa+ keeps this conversational context itself, so the host does too.
    next_beat: int | None = None
    # Plain user/assistant text turns for the LLM host; tool traffic is not kept.
    messages: list[dict[str, Any]] = field(default_factory=list)

    def remember_exchange(self, said: str, replied: str) -> None:
        self.messages += [
            {"role": "user", "content": [{"text": said}]},
            {"role": "assistant", "content": [{"text": replied}]},
        ]
        self.messages = self.messages[-MAX_HISTORY_MESSAGES:]

    def context_note(self) -> str:
        """What is on screen, for a model host: the ids behind "the second one" or "continue".

        Alexa+ keeps earlier tool results in the conversation; history here is plain text,
        so the model is told the listed stories and the story being heard, with their ids.
        """
        notes = []
        if self.last_stories:
            listed = "; ".join(
                f"{n}. {item['title']} (story_id {item['story_id']})"
                for n, item in enumerate(self.last_stories, start=1)
            )
            notes.append(f"Stories listed on screen: {listed}.")
        if self.last_story_id:
            notes.append(f"Story being heard: story_id {self.last_story_id}.")
        return "\n\n[Conversation context] " + " ".join(notes) if notes else ""


class KeyValueStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ex: int) -> object: ...

    def delete(self, key: str) -> object: ...


class SessionStore:
    """Load and save session state; a Redis outage degrades to a fresh session."""

    def __init__(self, client: KeyValueStore | None = None) -> None:
        self.client = client or redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    @staticmethod
    def key(session_id: str) -> str:
        return f"greeo:simulator:{session_id}"

    def load(self, session_id: str) -> SessionState:
        try:
            raw = self.client.get(self.key(session_id))
        except redis.RedisError:
            logger.warning("Simulator session store unavailable.", exc_info=True)
            return SessionState()
        if not raw:
            return SessionState()
        known = {f.name for f in fields(SessionState)}
        return SessionState(**{k: v for k, v in json.loads(raw).items() if k in known})

    def save(self, session_id: str, state: SessionState) -> None:
        try:
            self.client.set(
                self.key(session_id),
                json.dumps(asdict(state)),
                ex=settings.SIMULATOR_SESSION_SECONDS,
            )
        except redis.RedisError:
            logger.warning("Could not save simulator session.", exc_info=True)

    def clear(self, session_id: str) -> None:
        try:
            self.client.delete(self.key(session_id))
        except redis.RedisError:
            logger.warning("Could not clear simulator session.", exc_info=True)
