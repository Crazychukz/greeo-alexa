"""Small HTTPX adapter for RSS/Atom feeds; it never follows article links."""

from __future__ import annotations

from typing import Protocol

import httpx
from django.conf import settings


class HTTPResponse(Protocol):
    """The narrow response interface used by the ingestion service and tests."""

    status_code: int
    headers: object
    content: bytes


class HTTPClient(Protocol):
    """The narrow request interface that makes all tests network-free."""

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> HTTPResponse: ...


class RSSClient:
    """Issue a single polite feed request with an explicit timeout."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(follow_redirects=True)

    def get(self, url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        return self.client.get(url, headers=headers, timeout=timeout)

    def close(self) -> None:
        """Release pooled connections; each fetch builds and closes its own client."""
        self.client.close()


def request_headers(etag: str, last_modified: str) -> dict[str, str]:
    """Build conditional headers without pretending to be a browser."""
    headers = {
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9",
        "User-Agent": f"GreeoBot/0.1 (+{settings.GREEO_CONTACT_EMAIL})",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers
