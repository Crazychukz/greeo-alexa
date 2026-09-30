"""Fast builders for many published synthetic stories (pagination and latency tests)."""

from __future__ import annotations

from apps.stories.models import Story, StoryTelling
from django.utils import timezone

from tests.factories import (
    ArticleFactory,
    StoryContextFactory,
    StoryFactFactory,
    StoryFactory,
    StoryTellingFactory,
    TellingBeatFactory,
)


def published_story(title: str, *, region: str = "Synthetic Region", beats: int = 3) -> Story:
    story = StoryFactory(
        handle=title,
        region=region,
        status=Story.Status.PUBLISHED,
        published_at=timezone.now(),
    )
    fact = StoryFactFactory(story=story, order=1, text=f"SYNTHETIC. {title} was reported.")
    fact.articles.add(ArticleFactory())
    StoryContextFactory(story=story, order=1, text="SYNTHETIC. Some background.")
    telling = StoryTellingFactory(
        story=story,
        tone=StoryTelling.Tone.BALANCED,
        status=StoryTelling.Status.PUBLISHED,
        closing_kind=StoryTelling.ClosingKind.REFLECTION,
        moral="SYNTHETIC reflection.",
    )
    for order in range(1, beats + 1):
        TellingBeatFactory(telling=telling, order=order, text_template=f"Beat {order} of {title}.")
    return story


def many_stories(count: int, *, topic: str = "river crossing") -> list[Story]:
    return [published_story(f"SYNTHETIC EVENT {topic} {n}") for n in range(1, count + 1)]
