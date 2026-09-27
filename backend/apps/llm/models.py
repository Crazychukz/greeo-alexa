"""Auditable metadata for all future gateway calls."""

from __future__ import annotations

from django.db import models


class LLMCall(models.Model):
    class Backend(models.TextChoices):
        MOCK = "mock", "Mock"
        BEDROCK = "bedrock", "Bedrock"

    prompt_name = models.CharField(max_length=100)
    prompt_version = models.CharField(max_length=50)
    model = models.CharField(max_length=255)
    backend = models.CharField(max_length=10, choices=Backend.choices)
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    cost_estimate_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    ok = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    story = models.ForeignKey("stories.Story", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
