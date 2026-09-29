"""Per-user listening memory: what a user heard, prefers, stopped at and saved.

Every function takes the user explicitly and every query filters by that user, so one
listener can never read or change another's state. Identity itself is decided by the
caller (the MCP server's request authentication), never by a tool argument.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

import redis
from django.conf import settings
from django.db import transaction

from apps.stories.models import Story, StoryTelling
from apps.wisdom.themes import validate_theme_keys

from .models import EndUser, StoryEncounter

logger = logging.getLogger(__name__)

TONES = ("light", "balanced", "serious")
DEFAULT_TONE = "balanced"
# The showcase order for suggestions. It is never a required path: a listener may
# jump to any layer at any time.
LAYERS = ("tale", "closing", "proverbs", "facts", "context", "perspectives", "sources")
# Layers that come from a particular telling, so they change when the tone changes.
TELLING_LAYERS = ("tale", "closing", "proverbs")
SESSION_TTL_SECONDS = 30 * 60


class MemoryInputError(ValueError):
    """Raised for input a caller must correct, such as an unknown tone or layer."""


@dataclass(frozen=True)
class Preferences:
    tone: str | None = None
    regions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Suggestion:
    """The next thing Greeo could offer; a hint, never a gate."""

    layer: str
    label: str
    beat: int | None = None


@dataclass(frozen=True)
class StoryProgress:
    story_id: str
    handle: str
    saved: bool
    tone: str
    last_beat: int
    beats_total: int
    tale_completed: bool
    resume_hint: str


@dataclass(frozen=True)
class SessionContext:
    last_story_id: str | None = None
    last_options: list[str] = field(default_factory=list)


def get_or_create_user(external_id: str) -> EndUser:
    """Map an authenticated external identity to its local user row."""
    if not external_id or not external_id.strip():
        raise MemoryInputError("An external user id is required.")
    user, _ = EndUser.objects.get_or_create(external_id=external_id.strip())
    return user


# Preferences -------------------------------------------------------------------------


def get_preferences(user: EndUser) -> Preferences:
    stored = user.preferences or {}
    return Preferences(
        tone=stored.get("tone"),
        regions=list(stored.get("regions", [])),
        topics=list(stored.get("topics", [])),
    )


def update_preferences(
    user: EndUser,
    *,
    tone: str | None = None,
    regions: list[str] | None = None,
    topics: list[str] | None = None,
) -> Preferences:
    """Change only the dimensions supplied, so "make it serious" leaves regions alone."""
    changes: dict[str, object] = {}
    if tone is not None:
        changes["tone"] = _valid_tone(tone)
    if regions is not None:
        changes["regions"] = _clean_list(regions)
    if topics is not None:
        cleaned = _clean_list(topics)
        try:
            validate_theme_keys(cleaned)
        except ValueError as error:
            raise MemoryInputError(str(error)) from error
        changes["topics"] = cleaned
    if changes:
        with transaction.atomic():
            locked = EndUser.objects.select_for_update().get(pk=user.pk)
            locked.preferences = {**(locked.preferences or {}), **changes}
            locked.save(update_fields=["preferences"])
        user.preferences = locked.preferences
    return get_preferences(user)


def preferred_tone(user: EndUser, requested: str | None = None) -> str:
    """Tone argument, then the user's preference, then balanced."""
    if requested is not None:
        return _valid_tone(requested)
    return get_preferences(user).tone or DEFAULT_TONE


def _valid_tone(tone: str) -> str:
    if tone not in TONES:
        raise MemoryInputError(f"Tone must be one of {', '.join(TONES)}.")
    return tone


def _clean_list(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


# Tale progress and layers ---------------------------------------------------------------


def published_telling(story: Story, tone: str | None) -> StoryTelling | None:
    """The telling in the requested tone, falling back to balanced, then any published one."""
    tellings = {t.tone: t for t in story.tellings.filter(status=StoryTelling.Status.PUBLISHED)}
    for candidate in (tone, DEFAULT_TONE, *TONES):
        if candidate in tellings:
            return tellings[candidate]
    return None


def record_beat(user: EndUser, story: Story, tone: str, beat: int) -> StoryEncounter:
    """Remember the furthest beat heard. Calling it twice with the same beat changes nothing.

    Switching tone restarts the tale: a different tone is a different telling, with its
    own beats and closing, so progress in one says nothing about the other.
    """
    telling = story.tellings.filter(tone=tone, status=StoryTelling.Status.PUBLISHED).first()
    if telling is None:
        raise MemoryInputError(f"This story has no published {tone} telling.")
    total = telling.beats.count()
    if not 1 <= beat <= total:
        raise MemoryInputError(f"Beat must be between 1 and {total}.")
    with transaction.atomic():
        encounter = _locked_encounter(user, story)
        if encounter.tone_heard and encounter.tone_heard != tone:
            _restart_tale(encounter)
        encounter.tone_heard = tone
        encounter.last_beat = max(encounter.last_beat, beat)
        encounter.last_layer = "tale"
        if encounter.last_beat >= total:
            encounter.tale_completed = True
            _add_layer(encounter, "tale")
        encounter.save()
    return encounter


def mark_layer_explored(user: EndUser, story: Story, layer: str) -> StoryEncounter:
    """Note a truth layer the user opened, in any order."""
    if layer not in LAYERS:
        raise MemoryInputError(f"Layer must be one of {', '.join(LAYERS)}.")
    with transaction.atomic():
        encounter = _locked_encounter(user, story)
        _add_layer(encounter, layer)
        encounter.last_layer = layer
        encounter.save()
    return encounter


def available_layers(story: Story, tone: str | None = None) -> list[str]:
    """Layers with content for this story, in showcase order."""
    telling = published_telling(story, tone)
    has_content = {
        "tale": telling is not None,
        "closing": bool(
            telling
            and telling.closing_kind != StoryTelling.ClosingKind.NONE
            and telling.moral.strip()
        ),
        "proverbs": bool(telling and telling.proverb_links.exists()),
        "facts": story.facts.exists(),
        "context": story.context_items.exists(),
        "perspectives": story.perspectives.exists(),
        "sources": story.facts.filter(articles__isnull=False).exists(),
    }
    return [layer for layer in LAYERS if has_content[layer]]


def next_layer_suggestion(user: EndUser, story: Story) -> Suggestion | None:
    """Offer an unfinished tale first, then the next unexplored layer with content.

    Because the tale comes first, "the proverb explained" is only suggested once the
    listener has heard the proverb; asking for it directly still always works.
    """
    encounter = StoryEncounter.objects.filter(user=user, story=story).first()
    tone = (encounter.tone_heard if encounter else "") or preferred_tone(user)
    telling = published_telling(story, tone)
    explored = set(encounter.layers_explored) if encounter else set()

    if telling is not None and not (encounter and encounter.tale_completed):
        total = telling.beats.count()
        if encounter and encounter.last_beat > 0:
            next_beat = min(encounter.last_beat + 1, total)
            return Suggestion("tale", f"continue at beat {next_beat}", beat=next_beat)
        return Suggestion("tale", "hear the tale", beat=1)

    for layer in available_layers(story, telling.tone if telling else tone):
        if layer not in explored:
            return Suggestion(layer, _layer_label(layer, telling))
    return None


# The one spoken label per layer, shared with the MCP tools so an option is never
# offered twice under two names.
LAYER_LABELS = {
    "tale": "hear the tale",
    "closing": "the closing thought",
    "proverbs": "the proverb explained",
    "facts": "the facts",
    "context": "the background",
    "perspectives": "different perspectives",
    "sources": "the sources",
}


def _layer_label(layer: str, telling: StoryTelling | None) -> str:
    if layer == "closing" and telling is not None:
        return f"the {telling.closing_kind}"
    return LAYER_LABELS[layer]


def explored_layers(user: EndUser, story: Story) -> set[str]:
    encounter = StoryEncounter.objects.filter(user=user, story=story).first()
    return set(encounter.layers_explored) if encounter else set()


def _locked_encounter(user: EndUser, story: Story) -> StoryEncounter:
    """Row-lock the user's encounter so concurrent calls cannot lose progress."""
    StoryEncounter.objects.get_or_create(user=user, story=story)
    return StoryEncounter.objects.select_for_update().get(user=user, story=story)


def _restart_tale(encounter: StoryEncounter) -> None:
    """Forget progress in the old telling; story-level layers such as facts stay explored."""
    encounter.last_beat = 0
    encounter.tale_completed = False
    encounter.layers_explored = [
        layer for layer in encounter.layers_explored if layer not in TELLING_LAYERS
    ]


def _add_layer(encounter: StoryEncounter, layer: str) -> None:
    if layer not in encounter.layers_explored:
        encounter.layers_explored = [*encounter.layers_explored, layer]


# Saved and in-progress stories -----------------------------------------------------------


def save_for_later(user: EndUser, story: Story) -> StoryEncounter:
    with transaction.atomic():
        encounter = _locked_encounter(user, story)
        encounter.saved = True
        encounter.save()
    return encounter


def get_saved_stories(user: EndUser, limit: int = 5) -> list[StoryProgress]:
    """Saved stories plus the most recent unfinished one, newest first, each with a resume hint."""
    visible = Story.objects.listable().filter(status=Story.Status.PUBLISHED)
    encounters = list(
        StoryEncounter.objects.filter(user=user, story__in=visible)
        .select_related("story")
        .order_by("-heard_at")
    )
    saved = [e for e in encounters if e.saved]
    in_progress = next(
        (e for e in encounters if e.last_beat > 0 and not e.tale_completed and not e.saved),
        None,
    )
    chosen = ([in_progress] if in_progress else []) + saved
    return [_progress(encounter, user) for encounter in chosen[:limit]]


def _progress(encounter: StoryEncounter, user: EndUser) -> StoryProgress:
    story = encounter.story
    telling = published_telling(story, encounter.tone_heard or preferred_tone(user))
    total = telling.beats.count() if telling else 0
    last_beat = min(encounter.last_beat, total)
    if encounter.tale_completed:
        hint = "tale finished"
    elif last_beat == 0:
        hint = "start the tale"
    else:
        hint = f"continue at beat {last_beat + 1}"
    return StoryProgress(
        story_id=story.pk,
        handle=story.handle,
        saved=encounter.saved,
        tone=telling.tone if telling else "",
        last_beat=last_beat,
        beats_total=total,
        tale_completed=encounter.tale_completed,
        resume_hint=hint,
    )


# Transient session context (Redis) -------------------------------------------------------


class SessionStore(Protocol):
    def get(self, key: str) -> str | None: ...

    def set(self, key: str, value: str, ex: int) -> object: ...

    def delete(self, key: str) -> object: ...


def _default_store() -> SessionStore:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _session_key(user: EndUser) -> str:
    return f"greeo:session:{user.pk}"


def get_session_context(user: EndUser, store: SessionStore | None = None) -> SessionContext:
    """Return the last 30 minutes of conversational context, or an empty one.

    Session context is a convenience; if Redis is unavailable Greeo carries on without it.
    """
    try:
        raw = (store or _default_store()).get(_session_key(user))
    except redis.RedisError:
        logger.warning("Session context unavailable for user %s", user.pk, exc_info=True)
        return SessionContext()
    if not raw:
        return SessionContext()
    data = json.loads(raw)
    return SessionContext(
        last_story_id=data.get("last_story_id"), last_options=list(data.get("last_options", []))
    )


def update_session_context(
    user: EndUser,
    *,
    last_story_id: str | None = None,
    last_options: list[str] | None = None,
    store: SessionStore | None = None,
) -> SessionContext:
    """Merge the supplied fields and restart the 30-minute window."""
    store = store or _default_store()
    current = get_session_context(user, store)
    updated = SessionContext(
        last_story_id=last_story_id if last_story_id is not None else current.last_story_id,
        last_options=last_options if last_options is not None else current.last_options,
    )
    payload = {"last_story_id": updated.last_story_id, "last_options": updated.last_options}
    try:
        store.set(_session_key(user), json.dumps(payload), ex=SESSION_TTL_SECONDS)
    except redis.RedisError:
        logger.warning("Could not store session context for user %s", user.pk, exc_info=True)
    return updated


def reset_context(
    user: EndUser, *, forget_history: bool = False, store: SessionStore | None = None
) -> None:
    """Clear transient context. History, saves and preferences go only when asked."""
    try:
        (store or _default_store()).delete(_session_key(user))
    except redis.RedisError:
        logger.warning("Could not clear session context for user %s", user.pk, exc_info=True)
    if forget_history:
        with transaction.atomic():
            StoryEncounter.objects.filter(user=user).delete()
            EndUser.objects.filter(pk=user.pk).update(preferences={})
        user.preferences = {}
