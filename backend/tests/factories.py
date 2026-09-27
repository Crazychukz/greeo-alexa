"""Synthetic-only factories; never use them to represent real events or proverbs."""

from __future__ import annotations

import factory
from apps.core.models import AuditEvent, PipelineRun, StageTrace
from apps.llm.models import LLMCall
from apps.memory.models import EndUser, Follow, RecallItem, StoryEncounter, StoryUpdate
from apps.news.models import Article, FetchLog, SourceFeed
from apps.stories.models import (
    Story,
    StoryContext,
    StoryFact,
    StoryPerspective,
    StoryTelling,
    TellingBeat,
    TellingProverb,
)
from apps.wisdom.models import Proverb


class SourceFeedFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SourceFeed

    name = factory.Sequence(lambda n: f"Synthetic Publisher {n}")
    feed_url = factory.Sequence(lambda n: f"https://synthetic-{n}.invalid/feed")
    region = "Synthetic Region"
    language = "en"
    terms_url = factory.Sequence(lambda n: f"https://synthetic-{n}.invalid/terms")


class ArticleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Article

    source = factory.SubFactory(SourceFeedFactory)
    evidence_kind = Article.EvidenceKind.CURATED
    url_clean = factory.Sequence(lambda n: f"https://synthetic.invalid/article/{n}")
    url_hash = factory.Sequence(lambda n: f"synthetic-hash-{n}")
    title = factory.Sequence(lambda n: f"SYNTHETIC EVENT {n}")
    snippet = "Synthetic evidence note."
    language = "en"
    region_tags = ["Synthetic Region"]


class FetchLogFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FetchLog

    source = factory.SubFactory(SourceFeedFactory)
    outcome = FetchLog.Outcome.OK


class ProverbFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Proverb

    original_text = factory.Sequence(lambda n: f"TEST PROVERB {n}")
    language = "Test language"
    spoken_form = factory.Sequence(lambda n: f"Test proverb spoken form {n}")
    meaning_note = "Synthetic meaning note."
    culture = "Test culture"
    region = "Synthetic Region"
    source_citation = "Synthetic source one"
    second_source_citation = "Synthetic source two"
    license = "Synthetic test license"
    verification_status = Proverb.VerificationStatus.VERIFIED
    themes = ["cooperation"]


class StoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Story

    is_synthetic = True
    handle = factory.Sequence(lambda n: f"SYNTHETIC EVENT {n}")
    region = "Synthetic Region"
    themes = ["cooperation"]


class StoryFactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoryFact

    story = factory.SubFactory(StoryFactory)
    order = factory.Sequence(lambda n: n + 1)
    text = "Synthetic cited fact."


class StoryContextFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoryContext

    story = factory.SubFactory(StoryFactory)
    order = factory.Sequence(lambda n: n + 1)
    kind = StoryContext.Kind.BACKGROUND
    text = "Synthetic context."


class StoryPerspectiveFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoryPerspective

    story = factory.SubFactory(StoryFactory)
    order = factory.Sequence(lambda n: n + 1)
    label = "Synthetic perspective"
    summary = "Synthetic perspective summary."


class StoryTellingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoryTelling

    story = factory.SubFactory(StoryFactory)
    tone = StoryTelling.Tone.BALANCED


class TellingBeatFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TellingBeat

    telling = factory.SubFactory(StoryTellingFactory)
    order = factory.Sequence(lambda n: n + 1)
    text_template = "A synthetic beat."


class TellingProverbFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TellingProverb

    telling = factory.SubFactory(StoryTellingFactory)
    proverb = factory.SubFactory(ProverbFactory)
    slot = factory.Sequence(lambda n: f"P{n + 1}")
    role = TellingProverb.Role.TURN


class EndUserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EndUser

    external_id = factory.Sequence(lambda n: f"synthetic-user-{n}")
    display_name = "Synthetic User"


class StoryEncounterFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoryEncounter

    user = factory.SubFactory(EndUserFactory)
    story = factory.SubFactory(StoryFactory)


class RecallItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RecallItem

    user = factory.SubFactory(EndUserFactory)
    story = factory.SubFactory(StoryFactory)


class FollowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Follow

    user = factory.SubFactory(EndUserFactory)
    story = factory.SubFactory(StoryFactory)


class StoryUpdateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StoryUpdate

    story = factory.SubFactory(StoryFactory)
    summary = "Synthetic update."


class PipelineRunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PipelineRun


class AuditEventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditEvent

    actor = "synthetic-user"
    action = "synthetic_action"
    target_type = "Synthetic"
    target_id = "synthetic-target"


class StageTraceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StageTrace

    stage = "synthetic_stage"
    status = StageTrace.Status.OK


class LLMCallFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = LLMCall

    prompt_name = "synthetic_prompt"
    prompt_version = "v1"
    model = "synthetic-model"
    backend = LLMCall.Backend.MOCK
    ok = True
