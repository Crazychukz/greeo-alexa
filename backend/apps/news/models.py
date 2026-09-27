"""Evidence metadata models. Article bodies are deliberately never stored."""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MaxLengthValidator
from django.db import models


class SourceFeed(models.Model):
    class UsePolicy(models.TextChoices):
        HEADLINE_SNIPPET_ONLY = "headline_snippet_only", "Headline and snippet only"
        BLOCKED = "blocked", "Blocked"

    class CircuitState(models.TextChoices):
        CLOSED = "closed", "Closed"
        OPEN = "open", "Open"

    name = models.CharField(max_length=150)
    feed_url = models.URLField(unique=True)
    region = models.CharField(max_length=100)
    language = models.CharField(max_length=16)
    terms_url = models.URLField()
    terms_reviewed_at = models.DateTimeField(null=True, blank=True)
    use_policy = models.CharField(
        max_length=24, choices=UsePolicy.choices, default=UsePolicy.BLOCKED
    )
    attribution_text = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=False)
    min_interval_minutes = models.PositiveIntegerField(default=30)
    last_fetched_at = models.DateTimeField(null=True, blank=True)
    etag = models.CharField(max_length=255, blank=True)
    last_modified = models.CharField(max_length=255, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    circuit_state = models.CharField(
        max_length=8, choices=CircuitState.choices, default=CircuitState.CLOSED
    )
    circuit_opened_reason = models.TextField(blank=True)
    circuit_open_until = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return self.name


class Article(models.Model):
    class EvidenceKind(models.TextChoices):
        NEWS_SNIPPET = "news_snippet", "News snippet"
        REFERENCE = "reference", "Reference"
        CURATED = "curated", "Curated"

    source = models.ForeignKey(SourceFeed, on_delete=models.PROTECT, related_name="articles")
    evidence_kind = models.CharField(max_length=16, choices=EvidenceKind.choices)
    url_clean = models.URLField(max_length=2048)
    url_hash = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=500)
    snippet = models.CharField(max_length=300, validators=[MaxLengthValidator(300)])
    published_at = models.DateTimeField(null=True, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    language = models.CharField(max_length=16)
    region_tags = ArrayField(models.CharField(max_length=100), default=list, blank=True)
    cluster_key = models.CharField(max_length=64, null=True, blank=True, db_index=True)

    class Meta:
        ordering = ("-published_at", "-fetched_at")

    def __str__(self) -> str:
        return self.title


class FetchLog(models.Model):
    class Outcome(models.TextChoices):
        OK = "ok", "OK"
        NOT_MODIFIED = "not_modified", "Not modified"
        BLOCKED = "blocked", "Blocked"
        RATE_LIMITED = "rate_limited", "Rate limited"
        ERROR = "error", "Error"
        SKIPPED_BY_POLICY = "skipped_by_policy", "Skipped by policy"

    source = models.ForeignKey(SourceFeed, on_delete=models.CASCADE, related_name="fetch_logs")
    requested_at = models.DateTimeField(auto_now_add=True)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-requested_at",)
