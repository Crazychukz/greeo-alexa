"""Synthetic-only tests for policy-first RSS ingestion; no network is used."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import StringIO

import pytest
from apps.news.models import Article, FetchLog, SourceFeed
from apps.news.services import due_feed_ids, fetch_source, skip_reason
from apps.news.tasks import ingest_feed, poll_due_feeds
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from tests.factories import SourceFeedFactory

SYNTHETIC_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>SYNTHETIC FEED</title>
<item><title>SYNTHETIC EVENT: River Lantern</title>
<link>HTTPS://SYNTHETIC.invalid/Story?utm_source=test&amp;keep=yes#fragment</link>
<description><p>Synthetic &lt;b&gt;snippet&lt;/b&gt; %s</p></description>
<pubDate>Thu, 25 Sep 2026 12:00:00 GMT</pubDate></item>
</channel></rss>""" % (b"word " * 100)


@dataclass
class FakeResponse:
    status_code: int
    content: bytes = b""
    headers: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {"Content-Type": "application/rss+xml"}


class FakeClient:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "headers": headers, "timeout": timeout})
        return next(self.responses)


class FakeGuard:
    def __init__(self) -> None:
        self.completed = 0

    def acquire(self, source: SourceFeed) -> str:
        del source
        return "synthetic-lock"

    def complete(self, source: SourceFeed, lock_key: str) -> None:
        del source, lock_key
        self.completed += 1


def approved_source(**kwargs) -> SourceFeed:
    return SourceFeedFactory(
        active=True,
        terms_reviewed_at=timezone.now(),
        use_policy=SourceFeed.UsePolicy.HEADLINE_SNIPPET_ONLY,
        **kwargs,
    )


@pytest.mark.django_db
def test_rss_normalises_dedupes_and_truncates_without_article_fetches() -> None:
    source = approved_source(etag="old-tag", last_modified="Wed, 24 Sep 2026 12:00:00 GMT")
    client = FakeClient([FakeResponse(200, SYNTHETIC_RSS, {"ETag": "new-tag"})])

    result = fetch_source(source, client=client, guard=FakeGuard())

    assert result.new == 1
    article = Article.objects.get()
    assert article.url_clean == "https://synthetic.invalid/Story?keep=yes"
    assert len(article.snippet) == 300
    assert article.published_at == datetime(2026, 9, 25, 12, tzinfo=UTC)
    assert article.region_tags == [source.region]
    headers = client.calls[0]["headers"]
    assert headers["If-None-Match"] == "old-tag"
    assert headers["If-Modified-Since"] == "Wed, 24 Sep 2026 12:00:00 GMT"
    assert headers["User-Agent"].startswith("GreeoBot/0.1 (+")

    source.refresh_from_db()
    source.last_fetched_at = timezone.now() - timedelta(minutes=31)
    source.save(update_fields=["last_fetched_at"])
    duplicate = fetch_source(
        source, client=FakeClient([FakeResponse(200, SYNTHETIC_RSS)]), guard=FakeGuard()
    )
    assert duplicate.duplicate == 1
    assert Article.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("status", [403, 429])
def test_403_or_429_open_circuit_without_retry(status: int) -> None:
    source = approved_source()
    client = FakeClient([FakeResponse(status, headers={"Retry-After": "120"})])

    result = fetch_source(source, client=client, guard=FakeGuard())

    source.refresh_from_db()
    assert result.error == 1
    assert len(client.calls) == 1
    assert source.circuit_state == SourceFeed.CircuitState.OPEN
    assert source.circuit_open_until is not None
    assert FetchLog.objects.get().outcome == (
        FetchLog.Outcome.BLOCKED if status == 403 else FetchLog.Outcome.RATE_LIMITED
    )


@pytest.mark.django_db
def test_not_modified_updates_audit_without_parsing_or_articles() -> None:
    source = approved_source()

    result = fetch_source(source, client=FakeClient([FakeResponse(304)]), guard=FakeGuard())

    assert result.not_modified == 1
    assert Article.objects.count() == 0
    assert FetchLog.objects.get().outcome == FetchLog.Outcome.NOT_MODIFIED


@pytest.mark.django_db
def test_policy_skip_makes_no_request_when_terms_are_not_reviewed() -> None:
    source = SourceFeedFactory(active=True, terms_reviewed_at=None)
    client = FakeClient([])

    result = fetch_source(source, client=client, guard=FakeGuard())

    assert result.skipped == 1
    assert client.calls == []
    assert FetchLog.objects.get().outcome == FetchLog.Outcome.SKIPPED_BY_POLICY


@pytest.mark.django_db
def test_5xx_uses_bounded_backoff_then_counts_one_failure() -> None:
    source = approved_source()
    client = FakeClient([FakeResponse(503), FakeResponse(503), FakeResponse(503)])
    delays: list[int] = []

    result = fetch_source(source, client=client, guard=FakeGuard(), sleep=delays.append)

    source.refresh_from_db()
    assert result.error == 1
    assert len(client.calls) == 3
    assert delays == [1, 2]
    assert source.consecutive_failures == 1


@pytest.mark.django_db
def test_challenge_page_opens_circuit_without_attempting_a_workaround() -> None:
    source = approved_source()
    response = FakeResponse(
        200,
        b"<html><title>CAPTCHA challenge</title></html>",
        {"Content-Type": "text/html"},
    )

    result = fetch_source(source, client=FakeClient([response]), guard=FakeGuard())

    source.refresh_from_db()
    assert result.error == 1
    assert source.circuit_state == SourceFeed.CircuitState.OPEN
    assert FetchLog.objects.get().outcome == FetchLog.Outcome.BLOCKED


@pytest.mark.django_db
def test_poll_due_feeds_enqueues_each_eligible_source_once(monkeypatch) -> None:
    source = approved_source()
    queued: list[int] = []
    monkeypatch.setattr(ingest_feed, "delay", queued.append)

    assert poll_due_feeds() == 1
    assert queued == [source.pk]


@pytest.mark.django_db
def test_load_sources_accepts_synthetic_example(tmp_path) -> None:
    source_file = tmp_path / "sources.yaml"
    source_file.write_text(
        """sources:
  - name: Synthetic Loader Feed
    feed_url: https://synthetic-loader.invalid/rss
    region: Synthetic Region
    language: en
    terms_url: https://synthetic-loader.invalid/terms
    terms_reviewed_at: 2026-09-25T00:00:00Z
    use_policy: headline_snippet_only
    attribution_text: Synthetic attribution
    active: false
    min_interval_minutes: 30
""",
        encoding="utf-8",
    )

    output = StringIO()
    call_command("load_sources", source_file, stdout=output)

    assert "created=1" in output.getvalue()
    assert SourceFeed.objects.get().name == "Synthetic Loader Feed"


@pytest.mark.django_db
def test_expired_circuit_is_closed_and_the_feed_is_polled_again() -> None:
    source = approved_source(
        circuit_state=SourceFeed.CircuitState.OPEN,
        circuit_open_until=timezone.now() - timedelta(minutes=1),
        circuit_opened_reason="HTTP 429; retry after earlier",
    )

    assert due_feed_ids() == [source.pk]
    source.refresh_from_db()
    assert source.circuit_state == SourceFeed.CircuitState.CLOSED
    assert source.circuit_open_until is None


@pytest.mark.django_db
def test_circuit_still_open_is_not_polled_and_skip_reason_never_writes() -> None:
    source = approved_source(
        circuit_state=SourceFeed.CircuitState.OPEN,
        circuit_open_until=timezone.now() - timedelta(minutes=1),
    )

    assert skip_reason(source) == "circuit is open"
    source.refresh_from_db()
    assert source.circuit_state == SourceFeed.CircuitState.OPEN

    source.circuit_open_until = timezone.now() + timedelta(minutes=30)
    source.save(update_fields=["circuit_open_until"])
    assert due_feed_ids() == []


@pytest.mark.django_db
@override_settings(NEWS_MAX_CONSECUTIVE_FAILURES=2, NEWS_MAX_5XX_RETRIES=0)
def test_repeated_failures_open_the_circuit() -> None:
    source = approved_source(min_interval_minutes=0)

    fetch_source(source, client=FakeClient([FakeResponse(404)]), guard=FakeGuard())
    source.refresh_from_db()
    assert source.circuit_state == SourceFeed.CircuitState.CLOSED

    fetch_source(source, client=FakeClient([FakeResponse(404)]), guard=FakeGuard())
    source.refresh_from_db()
    assert source.circuit_state == SourceFeed.CircuitState.OPEN
    assert source.circuit_opened_reason.startswith("2 consecutive failures; last: HTTP 404")
