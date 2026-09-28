"""Per-user memory: progress, layers, preferences, saves, session context and isolation."""

from __future__ import annotations

import pytest
import redis
from apps.memory import services
from apps.memory.models import StoryEncounter
from apps.memory.services import MemoryInputError
from apps.stories.models import Story, StoryTelling
from django.test import override_settings
from django.utils import timezone

from tests.factories import (
    ArticleFactory,
    EndUserFactory,
    StoryContextFactory,
    StoryFactFactory,
    StoryFactory,
    StoryPerspectiveFactory,
    StoryTellingFactory,
    TellingBeatFactory,
    TellingProverbFactory,
)

pytestmark = pytest.mark.django_db


class FakeStore:
    """In-memory stand-in for Redis that records the expiry it was given."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int) -> bool:
        self.values[key] = value
        self.expiry[key] = ex
        return True

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)


class BrokenStore:
    def get(self, key: str) -> str | None:
        raise redis.ConnectionError("synthetic outage")

    def set(self, key: str, value: str, ex: int) -> bool:
        raise redis.ConnectionError("synthetic outage")

    def delete(self, key: str) -> int:
        raise redis.ConnectionError("synthetic outage")


def make_story(
    *,
    beats: int = 4,
    tones: tuple[str, ...] = ("balanced",),
    closing_kind: str = StoryTelling.ClosingKind.REFLECTION,
    moral: str = "SYNTHETIC reflection.",
    proverb: bool = True,
    context: bool = True,
    perspectives: bool = True,
) -> Story:
    story = StoryFactory(status=Story.Status.PUBLISHED, published_at=timezone.now())
    StoryFactFactory(story=story).articles.add(ArticleFactory())
    for tone in tones:
        telling = StoryTellingFactory(
            story=story,
            tone=tone,
            status=StoryTelling.Status.PUBLISHED,
            closing_kind=closing_kind,
            moral=moral,
        )
        for order in range(1, beats + 1):
            TellingBeatFactory(telling=telling, order=order, text_template=f"Beat {order}.")
        if proverb:
            TellingProverbFactory(telling=telling, slot="P1")
    if context:
        StoryContextFactory(story=story)
    if perspectives:
        StoryPerspectiveFactory(story=story)
    return story


def test_resume_hint_after_beat_two_of_four() -> None:
    user, story = EndUserFactory(), make_story(beats=4)

    services.record_beat(user, story, "balanced", 1)
    services.record_beat(user, story, "balanced", 2)

    suggestion = services.next_layer_suggestion(user, story)
    assert (suggestion.layer, suggestion.label, suggestion.beat) == (
        "tale",
        "continue at beat 3",
        3,
    )
    [progress] = services.get_saved_stories(user)
    assert progress.resume_hint == "continue at beat 3"
    assert (progress.last_beat, progress.beats_total) == (2, 4)


def test_record_beat_is_idempotent_and_keeps_the_furthest_beat() -> None:
    user, story = EndUserFactory(), make_story(beats=4)

    services.record_beat(user, story, "balanced", 2)
    services.record_beat(user, story, "balanced", 2)
    services.record_beat(user, story, "balanced", 1)

    encounter = StoryEncounter.objects.get(user=user, story=story)
    assert encounter.last_beat == 2
    assert encounter.tale_completed is False
    assert encounter.layers_explored == []


def test_record_beat_rejects_out_of_range_beats_and_missing_tones() -> None:
    user, story = EndUserFactory(), make_story(beats=3)

    with pytest.raises(MemoryInputError, match="between 1 and 3"):
        services.record_beat(user, story, "balanced", 4)
    with pytest.raises(MemoryInputError, match="no published serious telling"):
        services.record_beat(user, story, "serious", 1)


def test_finishing_the_tale_then_suggests_the_closing() -> None:
    user, story = EndUserFactory(), make_story(beats=3)

    for beat in (1, 2, 3):
        services.record_beat(user, story, "balanced", beat)

    encounter = StoryEncounter.objects.get(user=user, story=story)
    assert encounter.tale_completed and encounter.layers_explored == ["tale"]
    suggestion = services.next_layer_suggestion(user, story)
    assert (suggestion.layer, suggestion.label) == ("closing", "the reflection")


def test_suggestions_skip_layers_without_content() -> None:
    user = EndUserFactory()
    story = make_story(
        beats=3,
        closing_kind=StoryTelling.ClosingKind.NONE,
        moral="",
        proverb=False,
        context=False,
        perspectives=False,
    )

    assert services.available_layers(story) == ["tale", "facts", "sources"]
    for beat in (1, 2, 3):
        services.record_beat(user, story, "balanced", beat)
    assert services.next_layer_suggestion(user, story).layer == "facts"
    services.mark_layer_explored(user, story, "facts")
    assert services.next_layer_suggestion(user, story).layer == "sources"
    services.mark_layer_explored(user, story, "sources")
    assert services.next_layer_suggestion(user, story) is None


def test_any_layer_can_be_opened_first_without_losing_tale_progress() -> None:
    user, story = EndUserFactory(), make_story(beats=4)

    services.record_beat(user, story, "balanced", 1)
    services.mark_layer_explored(user, story, "facts")

    assert services.next_layer_suggestion(user, story).label == "continue at beat 2"
    for beat in (2, 3, 4):
        services.record_beat(user, story, "balanced", beat)
    services.mark_layer_explored(user, story, "closing")
    services.mark_layer_explored(user, story, "proverbs")
    # Facts were already heard, so the next suggestion moves on to context.
    assert services.next_layer_suggestion(user, story).layer == "context"


def test_unknown_layer_is_rejected() -> None:
    with pytest.raises(MemoryInputError, match="Layer must be one of"):
        services.mark_layer_explored(EndUserFactory(), make_story(), "gossip")


def test_switching_tone_restarts_the_tale_but_keeps_story_layers() -> None:
    user = EndUserFactory()
    story = make_story(beats=4, tones=("balanced", "serious"))
    for beat in (1, 2, 3, 4):
        services.record_beat(user, story, "balanced", beat)
    for layer in ("closing", "proverbs", "facts", "context"):
        services.mark_layer_explored(user, story, layer)

    services.record_beat(user, story, "serious", 1)

    encounter = StoryEncounter.objects.get(user=user, story=story)
    assert (encounter.tone_heard, encounter.last_beat) == ("serious", 1)
    assert encounter.tale_completed is False
    assert encounter.layers_explored == ["facts", "context"]
    assert services.next_layer_suggestion(user, story).label == "continue at beat 2"
    [progress] = services.get_saved_stories(user)
    assert (progress.tone, progress.resume_hint) == ("serious", "continue at beat 2")


def test_hearing_a_later_beat_in_a_new_tone_starts_progress_there() -> None:
    user = EndUserFactory()
    story = make_story(beats=4, tones=("balanced", "serious"))
    services.record_beat(user, story, "balanced", 3)

    services.record_beat(user, story, "serious", 2)

    encounter = StoryEncounter.objects.get(user=user, story=story)
    assert (encounter.tone_heard, encounter.last_beat) == ("serious", 2)


def test_preferences_merge_without_overwriting_untouched_dimensions() -> None:
    user = EndUserFactory()

    services.update_preferences(user, regions=["Nigeria"], topics=["community"])
    services.update_preferences(user, tone="serious")
    preferences = services.update_preferences(user, regions=["Kenya", " Kenya ", ""])

    assert preferences == services.Preferences(
        tone="serious", regions=["Kenya"], topics=["community"]
    )
    user.refresh_from_db()
    assert services.get_preferences(user) == preferences


def test_preferences_reject_unknown_tone_and_topic() -> None:
    user = EndUserFactory()

    with pytest.raises(MemoryInputError, match="Tone must be one of"):
        services.update_preferences(user, tone="spooky")
    with pytest.raises(MemoryInputError, match="Unknown theme"):
        services.update_preferences(user, topics=["not_a_theme"])
    assert services.get_preferences(user) == services.Preferences()


def test_preferred_tone_uses_argument_then_preference_then_balanced() -> None:
    user = EndUserFactory()

    assert services.preferred_tone(user) == "balanced"
    services.update_preferences(user, tone="light")
    assert services.preferred_tone(user) == "light"
    assert services.preferred_tone(user, "serious") == "serious"


def test_saved_stories_include_saves_and_the_latest_unfinished_tale() -> None:
    user = EndUserFactory()
    saved, unfinished, finished = make_story(), make_story(beats=4), make_story(beats=1)

    services.save_for_later(user, saved)
    services.record_beat(user, unfinished, "balanced", 2)
    services.record_beat(user, finished, "balanced", 1)

    results = services.get_saved_stories(user)

    assert [r.story_id for r in results] == [unfinished.pk, saved.pk]
    assert results[1].saved and results[1].resume_hint == "start the tale"


def test_saved_stories_hide_synthetic_stories_when_not_allowed() -> None:
    user, story = EndUserFactory(), make_story()
    services.save_for_later(user, story)

    with override_settings(ALLOW_SYNTHETIC=False):
        assert services.get_saved_stories(user) == []
    with override_settings(ALLOW_SYNTHETIC=True):
        assert len(services.get_saved_stories(user)) == 1


def test_session_context_merges_and_expires_after_thirty_minutes() -> None:
    user, store = EndUserFactory(), FakeStore()

    services.update_session_context(user, last_story_id="st_example", store=store)
    context = services.update_session_context(
        user, last_options=["continue", "the facts"], store=store
    )

    assert context == services.SessionContext("st_example", ["continue", "the facts"])
    assert services.get_session_context(user, store) == context
    assert set(store.expiry.values()) == {30 * 60}


def test_session_context_survives_a_redis_outage() -> None:
    user = EndUserFactory()

    assert services.get_session_context(user, BrokenStore()) == services.SessionContext()
    services.update_session_context(user, last_story_id="st_example", store=BrokenStore())
    services.reset_context(user, store=BrokenStore())


def test_reset_clears_session_but_keeps_history_unless_asked() -> None:
    user, story, store = EndUserFactory(), make_story(), FakeStore()
    services.update_preferences(user, tone="serious")
    services.record_beat(user, story, "balanced", 2)
    services.save_for_later(user, story)
    services.update_session_context(user, last_story_id=story.pk, store=store)

    services.reset_context(user, store=store)

    assert services.get_session_context(user, store) == services.SessionContext()
    assert StoryEncounter.objects.get(user=user, story=story).saved is True
    assert services.get_preferences(user).tone == "serious"

    services.reset_context(user, forget_history=True, store=store)

    assert not StoryEncounter.objects.filter(user=user).exists()
    user.refresh_from_db()
    assert services.get_preferences(user) == services.Preferences()


def test_user_a_cannot_read_or_change_user_b_state() -> None:
    alice, bola, story, store = EndUserFactory(), EndUserFactory(), make_story(), FakeStore()
    services.record_beat(alice, story, "balanced", 2)
    services.save_for_later(alice, story)
    services.update_preferences(alice, tone="serious")
    services.update_session_context(alice, last_story_id=story.pk, store=store)

    assert services.get_saved_stories(bola) == []
    assert services.next_layer_suggestion(bola, story).label == "hear the tale"
    assert services.get_preferences(bola) == services.Preferences()
    assert services.get_session_context(bola, store) == services.SessionContext()

    services.record_beat(bola, story, "balanced", 4)
    services.reset_context(bola, forget_history=True, store=store)

    alice_encounter = StoryEncounter.objects.get(user=alice, story=story)
    assert (alice_encounter.last_beat, alice_encounter.saved) == (2, True)
    assert services.get_session_context(alice, store).last_story_id == story.pk
    alice.refresh_from_db()
    assert services.get_preferences(alice).tone == "serious"


def test_get_or_create_user_requires_an_identity() -> None:
    user = services.get_or_create_user(" listener-1 ")

    assert services.get_or_create_user("listener-1") == user
    with pytest.raises(MemoryInputError):
        services.get_or_create_user("  ")
