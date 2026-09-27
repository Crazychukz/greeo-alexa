"""Celery dispatch for compliant RSS feed ingestion."""

from __future__ import annotations

from celery import shared_task

from .models import SourceFeed
from .services import due_feed_ids, fetch_source


@shared_task(name="news.ingest_feed")
def ingest_feed(feed_id: int) -> dict[str, int]:
    """Perform one idempotent feed attempt; policy is rechecked in fetch_source."""
    source = SourceFeed.objects.filter(pk=feed_id).first()
    if source is None:
        return {"new": 0, "duplicate": 0, "error": 1, "skipped": 0, "not_modified": 0}
    return fetch_source(source).__dict__


@shared_task(name="news.poll_due_feeds")
def poll_due_feeds() -> int:
    """Enqueue at most one ingestion task per currently eligible feed."""
    feed_ids = due_feed_ids()
    for feed_id in feed_ids:
        ingest_feed.delay(feed_id)
    return len(feed_ids)
