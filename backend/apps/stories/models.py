"""Published story layers and precomputed voice tellings."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Count
from django.utils import timezone

from apps.core.ids import story_id

from .managers import StoryManager
from .voices import VoiceStyle, voice_for, voice_problems


class Story(models.Model):
    class ToneClass(models.TextChoices):
        NEUTRAL = "neutral", "Neutral"
        SENSITIVE = "sensitive", "Sensitive"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        VALIDATED = "validated", "Validated"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    id = models.CharField(primary_key=True, max_length=15, default=story_id, editable=False)
    cluster_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    is_synthetic = models.BooleanField(default=False)
    # A demo story (such as a friction-log tale) is told on request but is not news, so
    # it never appears among today's stories.
    is_demo = models.BooleanField(default=False)
    handle = models.CharField(max_length=120)
    tone_class = models.CharField(
        max_length=12, choices=ToneClass.choices, default=ToneClass.NEUTRAL
    )
    themes = ArrayField(models.CharField(max_length=80), default=list, blank=True)
    region = models.CharField(max_length=100)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    rejection_reasons = models.JSONField(default=list, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    last_updated_at = models.DateTimeField(auto_now=True)
    pipeline_run = models.ForeignKey(
        "core.PipelineRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="stories"
    )

    objects = StoryManager()

    class Meta:
        ordering = ("-published_at", "-last_updated_at")

    def __str__(self) -> str:
        return self.handle

    @transaction.atomic
    def publish(self) -> None:
        """Publish only a story whose evidence and telling invariants already hold."""
        cited_facts = self.facts.annotate(article_count=Count("articles")).filter(
            article_count__gte=1
        )
        if cited_facts.count() < 2:
            raise ValidationError("A published story needs at least two cited facts.")

        published_tellings = self.tellings.filter(status=StoryTelling.Status.PUBLISHED)
        if not published_tellings.exists():
            raise ValidationError("A published story needs at least one published telling.")

        for telling in published_tellings.prefetch_related("proverb_links__proverb"):
            if self.tone_class == self.ToneClass.SENSITIVE and telling.proverb_links.exists():
                raise ValidationError("Sensitive stories cannot publish tellings with proverbs.")
            if (
                self.tone_class == self.ToneClass.SENSITIVE
                and telling.tone == StoryTelling.Tone.LIGHT
            ):
                raise ValidationError("Sensitive stories cannot publish a light telling.")
            for link in telling.proverb_links.all():
                if not link.proverb_is_servable:
                    raise ValidationError("Published tellings may only use servable proverbs.")

        self.status = self.Status.PUBLISHED
        self.published_at = timezone.now()
        self.save(update_fields=["status", "published_at", "last_updated_at"])


class StoryFact(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="facts")
    order = models.PositiveSmallIntegerField()
    text = models.TextField()
    articles = models.ManyToManyField("news.Article", related_name="facts")

    class Meta:
        constraints = [models.UniqueConstraint(fields=("story", "order"), name="unique_fact_order")]
        ordering = ("order",)


class StoryContext(models.Model):
    class Kind(models.TextChoices):
        BACKGROUND = "background", "Background"
        WHY_IT_MATTERS = "why_it_matters", "Why it matters"
        CONSEQUENCE = "consequence", "Consequence"

    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="context_items")
    order = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=16, choices=Kind.choices)
    text = models.TextField()
    articles = models.ManyToManyField("news.Article", related_name="context_items")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("story", "order"), name="unique_context_order")
        ]
        ordering = ("order",)


class StoryPerspective(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="perspectives")
    order = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=120)
    summary = models.TextField()
    articles = models.ManyToManyField("news.Article", related_name="perspectives")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("story", "order"), name="unique_perspective_order")
        ]
        ordering = ("order",)


class StoryTelling(models.Model):
    class Tone(models.TextChoices):
        LIGHT = "light", "Light"
        BALANCED = "balanced", "Balanced"
        SERIOUS = "serious", "Serious"

    class ClosingKind(models.TextChoices):
        MORAL = "moral", "Moral"
        REFLECTION = "reflection", "Reflection"
        NONE = "none", "None"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CHECKED = "checked", "Checked"
        PUBLISHED = "published", "Published"
        REJECTED = "rejected", "Rejected"

    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="tellings")
    tone = models.CharField(max_length=10, choices=Tone.choices)
    closing_kind = models.CharField(
        max_length=10, choices=ClosingKind.choices, default=ClosingKind.REFLECTION
    )
    moral = models.CharField(max_length=200, blank=True)
    # The storyteller voice this telling was written in (see stories/voices.py). Blank
    # means the default voice for the tone.
    voice_style = models.CharField(max_length=24, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    is_curated = models.BooleanField(default=False)
    checker_report = models.JSONField(default=dict, blank=True)
    revision_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("story", "tone"), name="unique_story_tone")]

    def clean(self) -> None:
        if self.story.tone_class == Story.ToneClass.SENSITIVE and self.tone == self.Tone.LIGHT:
            raise ValidationError({"tone": "Light tone is not allowed for sensitive stories."})
        if self.voice_style:
            problems = voice_problems(self.voice_style, self.tone, self.story.tone_class)
            if problems:
                raise ValidationError({"voice_style": problems})

    @property
    def voice(self) -> VoiceStyle:
        """The stored voice when it fits this tone and story, else the default."""
        return voice_for(self.tone, self.story.tone_class, self.voice_style or None)


class TellingBeat(models.Model):
    telling = models.ForeignKey(StoryTelling, on_delete=models.CASCADE, related_name="beats")
    order = models.PositiveSmallIntegerField()
    text_template = models.TextField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("telling", "order"), name="unique_beat_order")
        ]
        ordering = ("order",)


class TellingProverb(models.Model):
    class Role(models.TextChoices):
        OPENING = "opening", "Opening"
        TURN = "turn", "Turn"
        CLOSING = "closing", "Closing"

    telling = models.ForeignKey(
        StoryTelling, on_delete=models.CASCADE, related_name="proverb_links"
    )
    proverb = models.ForeignKey(
        "wisdom.Proverb", on_delete=models.PROTECT, related_name="telling_links"
    )
    slot = models.CharField(max_length=16)
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("telling", "slot"), name="unique_telling_slot")
        ]

    @property
    def proverb_is_servable(self) -> bool:
        """Avoid trusting a stale relationship when publication checks a proverb."""
        return self.proverb.is_servable

    def clean(self) -> None:
        if self.telling.story.tone_class == Story.ToneClass.SENSITIVE:
            raise ValidationError("Sensitive stories cannot use proverbs.")
