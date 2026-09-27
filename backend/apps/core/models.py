"""Auditable process models shared by editorial applications."""

from __future__ import annotations

import uuid

from django.db import models


class PipelineRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        OK = "ok", "OK"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    stats = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.id} ({self.status})"


class AuditEvent(models.Model):
    actor = models.CharField(max_length=255)
    action = models.CharField(max_length=120)
    target_type = models.CharField(max_length=120)
    target_id = models.CharField(max_length=120)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.action}: {self.target_type}/{self.target_id}"


class StageTrace(models.Model):
    class Status(models.TextChoices):
        OK = "ok", "OK"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"
        RETRIED = "retried", "Retried"

    run = models.ForeignKey(PipelineRun, on_delete=models.SET_NULL, null=True, blank=True)
    story = models.ForeignKey("stories.Story", on_delete=models.SET_NULL, null=True, blank=True)
    stage = models.CharField(max_length=100)
    attempt = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=16, choices=Status.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    input_summary = models.TextField(blank=True)
    output_summary = models.TextField(blank=True)
    error = models.TextField(blank=True)
    host_mode = models.CharField(max_length=10, blank=True)

    class Meta:
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.stage} attempt {self.attempt}: {self.status}"
