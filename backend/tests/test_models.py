from __future__ import annotations

import pytest
from apps.stories.models import Story, StoryTelling
from apps.wisdom.models import Proverb
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.test import override_settings

from tests.factories import (
    ArticleFactory,
    ProverbFactory,
    StoryFactFactory,
    StoryFactory,
    StoryTellingFactory,
    TellingProverbFactory,
)

pytestmark = pytest.mark.skipif(
    connection.vendor != "postgresql",
    reason="Phase 2 uses PostgreSQL ArrayField constraints.",
)


@pytest.mark.django_db
def test_servable_proverbs_require_verified_status_and_tone_permission() -> None:
    good = ProverbFactory()
    ProverbFactory(verification_status=Proverb.VerificationStatus.SINGLE_SOURCE)
    ProverbFactory(verification_status=Proverb.VerificationStatus.DISPUTED)
    ProverbFactory(tone_ok=False)

    assert list(Proverb.objects.servable()) == [good]


@pytest.mark.django_db
def test_verified_proverb_requires_two_citations_in_validation_and_database() -> None:
    proverb = ProverbFactory.build(second_source_citation="")

    with pytest.raises(ValidationError):
        proverb.full_clean()
    with pytest.raises(IntegrityError):
        proverb.save(force_insert=True)


@pytest.mark.django_db
def test_listable_stories_hide_synthetic_by_default_and_allow_them_in_development() -> None:
    synthetic = StoryFactory(is_synthetic=True)
    real = StoryFactory(is_synthetic=False)

    with override_settings(ALLOW_SYNTHETIC=False):
        assert list(Story.objects.listable()) == [real]
    with override_settings(ALLOW_SYNTHETIC=True):
        assert set(Story.objects.listable()) == {synthetic, real}


@pytest.mark.django_db
def test_publish_requires_two_cited_facts_and_a_published_telling() -> None:
    story = StoryFactory()
    fact_one = StoryFactFactory(story=story, order=1)
    fact_one.articles.add(ArticleFactory())

    with pytest.raises(ValidationError, match="two cited facts"):
        story.publish()

    fact_two = StoryFactFactory(story=story, order=2)
    fact_two.articles.add(ArticleFactory())
    StoryTellingFactory(story=story, status=StoryTelling.Status.PUBLISHED)
    story.publish()

    story.refresh_from_db()
    assert story.status == Story.Status.PUBLISHED
    assert story.published_at is not None


@pytest.mark.django_db
def test_sensitive_telling_rejects_light_tone_and_any_proverb_at_publish() -> None:
    story = StoryFactory(tone_class=Story.ToneClass.SENSITIVE)
    light_telling = StoryTellingFactory(story=story, tone=StoryTelling.Tone.LIGHT)

    with pytest.raises(ValidationError, match="Light tone"):
        light_telling.full_clean()

    serious_telling = StoryTellingFactory(
        story=story, tone=StoryTelling.Tone.SERIOUS, status=StoryTelling.Status.PUBLISHED
    )
    link = TellingProverbFactory(telling=serious_telling)

    with pytest.raises(ValidationError, match="Sensitive stories"):
        link.full_clean()


@pytest.mark.django_db
def test_publishing_rejects_an_unservable_proverb_link() -> None:
    story = StoryFactory()
    for order in (1, 2):
        fact = StoryFactFactory(story=story, order=order)
        fact.articles.add(ArticleFactory())
    telling = StoryTellingFactory(story=story, status=StoryTelling.Status.PUBLISHED)
    proverb = ProverbFactory(verification_status=Proverb.VerificationStatus.SINGLE_SOURCE)
    TellingProverbFactory(telling=telling, proverb=proverb)

    with pytest.raises(ValidationError, match="servable proverbs"):
        story.publish()
