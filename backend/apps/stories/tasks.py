"""Celery dispatch for the editorial pipeline."""

from __future__ import annotations

from celery import shared_task
from django.conf import settings

from .pipeline import run_pipeline


@shared_task(name="stories.run_pipeline")
def run_pipeline_task() -> dict[str, int]:
    """Publish a few new stories per run; the daily token budget caps the total."""
    result = run_pipeline(settings.PIPELINE_STORIES_PER_RUN)
    return {"published": len(result.published), "rejected": len(result.rejected)}
