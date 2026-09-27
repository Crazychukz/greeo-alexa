"""Celery tasks owned by the core application."""

from celery import shared_task


@shared_task(name="core.ping")
def ping() -> str:
    """Provide a minimal task that proves worker discovery during Phase 1."""
    return "pong"
