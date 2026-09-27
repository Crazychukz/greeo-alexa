"""Policy-first RSS ingestion. This module never fetches article pages."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import redis
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .adapters.rss import HTTPClient, RSSClient, request_headers
from .models import Article, FetchLog, SourceFeed

TRACKING_KEYS = {"fbclid", "gclid", "ref"}
CHALLENGE_MARKERS = ("captcha", "cf-chl-", "cloudflare challenge", "access denied")


@dataclass(frozen=True)
class IngestResult:
    """Small, command-friendly summary of one feed attempt."""

    new: int = 0
    duplicate: int = 0
    error: int = 0
    skipped: int = 0
    not_modified: int = 0


class PlainTextParser(HTMLParser):
    """Strip feed-entry markup before storing a bounded source snippet."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def canonical_url(url: str) -> str:
    """Drop fragments and common tracking query fields while preserving content identity."""
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").lower()
    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    if parsed.username:
        netloc = f"{parsed.username}@{netloc}"
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and not key.lower().startswith("mc_")
            and key.lower() not in TRACKING_KEYS
        ],
        doseq=True,
    )
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, query, ""))


def url_digest(url: str) -> str:
    """Provide a stable dedupe key for a canonical URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def plain_snippet(value: str) -> str:
    """Store only plain text and at most the policy maximum of 300 characters."""
    parser = PlainTextParser()
    parser.feed(value)
    parser.close()
    return " ".join("".join(parser.parts).split())[:300]


def published_at(entry: Any) -> datetime | None:
    """Turn feedparser's parsed timestamp into an aware UTC datetime."""
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            return datetime(*value[:6], tzinfo=UTC)
    return None


def close_expired_circuit(source: SourceFeed, now: datetime | None = None) -> None:
    """Close a circuit whose retry deadline has passed so the feed can be polled again."""
    now = now or timezone.now()
    if (
        source.circuit_state == SourceFeed.CircuitState.OPEN
        and source.circuit_open_until
        and source.circuit_open_until <= now
    ):
        source.circuit_state = SourceFeed.CircuitState.CLOSED
        source.circuit_opened_reason = ""
        source.circuit_open_until = None
        source.consecutive_failures = 0
        source.save(
            update_fields=(
                "circuit_state",
                "circuit_opened_reason",
                "circuit_open_until",
                "consecutive_failures",
            )
        )


def skip_reason(source: SourceFeed, now: datetime | None = None) -> str | None:
    """Return a policy reason before any network request is permitted. Never writes."""
    now = now or timezone.now()
    if source.circuit_state == SourceFeed.CircuitState.OPEN:
        return "circuit is open"
    if not source.active:
        return "feed is inactive"
    if source.terms_reviewed_at is None:
        return "terms have not been reviewed"
    if source.use_policy == SourceFeed.UsePolicy.BLOCKED:
        return "source use policy is blocked"
    if (
        source.last_fetched_at
        and source.last_fetched_at + timedelta(minutes=source.min_interval_minutes) > now
    ):
        return "minimum fetch interval has not elapsed"
    return None


class RedisIngestionGuard:
    """Coordinate worker attempts without bypassing source-specific policy."""

    def __init__(self, client: redis.Redis | None = None) -> None:
        self.client = client or redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    def acquire(self, source: SourceFeed) -> str | None:
        """Return an acquired domain lock key, or None when another worker owns it."""
        host = (urlsplit(source.feed_url).hostname or "unknown").lower()
        feed_key = f"greeo:news:feed:{source.pk}"
        if self.client.exists(feed_key):
            return None
        lock_key = f"greeo:news:domain-lock:{host}"
        acquired = self.client.set(
            lock_key, str(source.pk), nx=True, ex=settings.NEWS_DOMAIN_LOCK_SECONDS
        )
        return lock_key if acquired else None

    def complete(self, source: SourceFeed, lock_key: str) -> None:
        """Set the feed interval only after a request, then release its short domain lock."""
        self.client.set(
            f"greeo:news:feed:{source.pk}",
            "1",
            ex=source.min_interval_minutes * 60,
        )
        self.client.delete(lock_key)

    def release(self, lock_key: str) -> None:
        """Release a lock when no network request could be made."""
        self.client.delete(lock_key)


def fetch_source(
    source: SourceFeed,
    *,
    client: HTTPClient | None = None,
    guard: RedisIngestionGuard | None = None,
    sleep: Any = time.sleep,
) -> IngestResult:
    """Fetch one approved feed, recording every result and never touching article pages."""
    close_expired_circuit(source)
    reason = skip_reason(source)
    if reason:
        FetchLog.objects.create(
            source=source, outcome=FetchLog.Outcome.SKIPPED_BY_POLICY, error=reason
        )
        return IngestResult(skipped=1)

    guard = guard or RedisIngestionGuard()
    try:
        lock_key = guard.acquire(source)
    except redis.RedisError as error:
        FetchLog.objects.create(
            source=source, outcome=FetchLog.Outcome.ERROR, error=f"Redis: {error}"
        )
        return IngestResult(error=1)
    if lock_key is None:
        FetchLog.objects.create(
            source=source,
            outcome=FetchLog.Outcome.SKIPPED_BY_POLICY,
            error="Redis feed interval or domain lock is active",
        )
        return IngestResult(skipped=1)

    owned_client = RSSClient() if client is None else None
    client = client or owned_client
    started = time.monotonic()
    try:
        response = _request_with_5xx_retry(source, client, sleep)
        source.last_fetched_at = timezone.now()
        if response.status_code == 304:
            source.consecutive_failures = 0
            source.save(update_fields=("last_fetched_at", "consecutive_failures"))
            FetchLog.objects.create(
                source=source,
                status_code=304,
                outcome=FetchLog.Outcome.NOT_MODIFIED,
                latency_ms=elapsed_ms(started),
            )
            return IngestResult(not_modified=1)
        if response.status_code in {403, 429}:
            _open_circuit(
                source,
                reason=f"HTTP {response.status_code}",
                retry_after=response.headers.get("Retry-After", ""),
            )
            FetchLog.objects.create(
                source=source,
                status_code=response.status_code,
                outcome=(
                    FetchLog.Outcome.RATE_LIMITED
                    if response.status_code == 429
                    else FetchLog.Outcome.BLOCKED
                ),
                latency_ms=elapsed_ms(started),
                error=source.circuit_opened_reason,
            )
            return IngestResult(error=1)
        if response.status_code >= 400:
            _record_failure(source, f"HTTP {response.status_code}")
            FetchLog.objects.create(
                source=source,
                status_code=response.status_code,
                outcome=FetchLog.Outcome.ERROR,
                latency_ms=elapsed_ms(started),
                error=f"HTTP {response.status_code}",
            )
            return IngestResult(error=1)
        if _looks_like_challenge(response):
            _open_circuit(
                source, reason=f"HTTP {response.status_code}; challenge response detected"
            )
            FetchLog.objects.create(
                source=source,
                status_code=response.status_code,
                outcome=FetchLog.Outcome.BLOCKED,
                latency_ms=elapsed_ms(started),
                error=source.circuit_opened_reason,
            )
            return IngestResult(error=1)

        result = _store_entries(source, response.content)
        source.etag = response.headers.get("ETag", source.etag)
        source.last_modified = response.headers.get("Last-Modified", source.last_modified)
        source.consecutive_failures = 0
        source.save(
            update_fields=("last_fetched_at", "etag", "last_modified", "consecutive_failures")
        )
        FetchLog.objects.create(
            source=source,
            status_code=response.status_code,
            outcome=FetchLog.Outcome.OK,
            latency_ms=elapsed_ms(started),
        )
        return result
    except Exception as error:
        _record_failure(source, str(error))
        FetchLog.objects.create(
            source=source,
            outcome=FetchLog.Outcome.ERROR,
            latency_ms=elapsed_ms(started),
            error=str(error)[:2000],
        )
        return IngestResult(error=1)
    finally:
        if owned_client is not None:
            owned_client.close()
        try:
            guard.complete(source, lock_key)
        except redis.RedisError:
            pass


def _request_with_5xx_retry(source: SourceFeed, client: HTTPClient, sleep: Any) -> Any:
    """Retry server failures only; 403/429 are returned immediately for policy handling."""
    for attempt in range(settings.NEWS_MAX_5XX_RETRIES + 1):
        response = client.get(
            source.feed_url,
            headers=request_headers(source.etag, source.last_modified),
            timeout=float(settings.NEWS_HTTP_TIMEOUT_SECONDS),
        )
        if response.status_code < 500 or attempt == settings.NEWS_MAX_5XX_RETRIES:
            return response
        sleep(2**attempt)
    raise AssertionError("unreachable")  # pragma: no cover


def _store_entries(source: SourceFeed, payload: bytes) -> IngestResult:
    """Parse response bytes and create only metadata allowed by the evidence policy."""
    parsed = feedparser.parse(payload)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        raise ValueError("Feed parsing failed and produced no entries")
    new = duplicate = 0
    with transaction.atomic():
        for entry in parsed.entries:
            link = entry.get("link", "")
            title = plain_snippet(entry.get("title", ""))
            if not link or not title:
                continue
            clean = canonical_url(link)
            digest = url_digest(clean)
            snippet = plain_snippet(
                entry.get("summary", entry.get("description", entry.get("title", "")))
            )
            try:
                _, created = Article.objects.get_or_create(
                    url_hash=digest,
                    defaults={
                        "source": source,
                        "evidence_kind": Article.EvidenceKind.NEWS_SNIPPET,
                        "url_clean": clean,
                        "title": title[:500],
                        "snippet": snippet,
                        "published_at": published_at(entry),
                        "language": entry.get("language", source.language)[:16],
                        "region_tags": [source.region],
                    },
                )
            except IntegrityError:
                created = False
            if created:
                new += 1
            else:
                duplicate += 1
    return IngestResult(new=new, duplicate=duplicate)


def _record_failure(source: SourceFeed, reason: str) -> None:
    """Count a failure, opening the circuit once a feed keeps failing."""
    source.last_fetched_at = timezone.now()
    source.consecutive_failures += 1
    source.save(update_fields=("last_fetched_at", "consecutive_failures"))
    if source.consecutive_failures >= settings.NEWS_MAX_CONSECUTIVE_FAILURES:
        _open_circuit(
            source,
            reason=f"{source.consecutive_failures} consecutive failures; last: {reason[:200]}",
        )


def _open_circuit(source: SourceFeed, *, reason: str, retry_after: str = "") -> None:
    """Block further fetches, retaining any server-provided retry delay."""
    until = retry_after_deadline(retry_after)
    if until is None:
        until = timezone.now() + timedelta(minutes=settings.NEWS_CIRCUIT_OPEN_MINUTES)
    source.circuit_state = SourceFeed.CircuitState.OPEN
    source.circuit_open_until = until
    source.circuit_opened_reason = f"{reason}; retry after {until.isoformat()}"
    source.last_fetched_at = timezone.now()
    source.save(
        update_fields=(
            "circuit_state",
            "circuit_open_until",
            "circuit_opened_reason",
            "last_fetched_at",
        )
    )


def retry_after_deadline(value: str) -> datetime | None:
    """Support both Retry-After seconds and HTTP-date forms."""
    if not value:
        return None
    if value.isdigit():
        return timezone.now() + timedelta(seconds=int(value))
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed else None


def _looks_like_challenge(response: Any) -> bool:
    """Recognise challenge pages so the project never tries to work around them."""
    content_type = response.headers.get("Content-Type", "").lower()
    if "html" not in content_type:
        return False
    sample = response.content[:4096].decode("utf-8", errors="ignore").lower()
    return any(marker in sample for marker in CHALLENGE_MARKERS)


def elapsed_ms(started: float) -> int:
    """Produce an integer audit value suitable for FetchLog."""
    return max(0, round((time.monotonic() - started) * 1000))


def due_feed_ids(now: datetime | None = None) -> list[int]:
    """Return feeds eligible for Celery dispatch; final checks remain in fetch_source."""
    now = now or timezone.now()
    feeds = SourceFeed.objects.filter(
        active=True,
        terms_reviewed_at__isnull=False,
        use_policy=SourceFeed.UsePolicy.HEADLINE_SNIPPET_ONLY,
    )
    eligible = []
    for feed in feeds:
        close_expired_circuit(feed, now)
        if skip_reason(feed, now) is None:
            eligible.append(feed.pk)
    return eligible
