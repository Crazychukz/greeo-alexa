"""The HTTP gate in front of the MCP endpoint: reject bad tokens, limit request rates.

Guests (no Authorization header) pass through, because story tools need no identity. A
token that is present but unknown or revoked gets HTTP 401, as the MCP authorization
spec and Alexa+ both expect ("Invalid or expired tokens MUST receive a HTTP 401
response"). The rate limit is deliberately simple: a per-minute count per token, or per
client address for guests, to blunt abuse of a public demo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Protocol

import redis
from asgiref.sync import sync_to_async
from django.conf import settings
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from apps.memory.tokens import user_for_token

from .identity import bearer_token

logger = logging.getLogger(__name__)
WINDOW_SECONDS = 60


class Counter(Protocol):
    def incr(self, key: str) -> int: ...

    def expire(self, key: str, seconds: int) -> object: ...


def rate_counter() -> Counter:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def over_limit(bucket: str, counter: Counter | None = None) -> bool:
    """Count this request in the current minute; True when the bucket is over its limit."""
    limit = settings.MCP_RATE_LIMIT_PER_MINUTE
    if limit <= 0:
        return False
    key = f"greeo:rate:{bucket}:{int(time.time() // WINDOW_SECONDS)}"
    try:
        counter = counter or rate_counter()
        count = int(counter.incr(key))
        if count == 1:
            counter.expire(key, WINDOW_SECONDS * 2)
    except redis.RedisError:
        logger.warning("Rate limiter unavailable; allowing the request.", exc_info=True)
        return False
    return count > limit


def bucket_for(token: str | None, scope: Scope) -> str:
    """A short, non-reversible name for the caller: never the token itself."""
    if token:
        return "t:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    client = scope.get("client") or ("unknown", 0)
    return "a:" + hashlib.sha256(str(client[0]).encode("utf-8")).hexdigest()[:16]


class IdentityGate:
    """ASGI middleware applied to the MCP endpoint only."""

    def __init__(self, app: ASGIApp, path: str = "/mcp") -> None:
        self.app = app
        self.path = path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != self.path:
            await self.app(scope, receive, send)
            return
        token = bearer_token(dict(Headers(scope=scope).items()))
        if token is not None:
            user = await sync_to_async(user_for_token, thread_sensitive=True)(token)
            if user is None:
                await _reply(send, 401, "unauthorized", "This access token is not valid.")
                return
        if await sync_to_async(over_limit, thread_sensitive=True)(bucket_for(token, scope)):
            await _reply(
                send, 429, "rate_limited", "Too many requests. Please wait a minute.",
                extra_headers=[(b"retry-after", str(WINDOW_SECONDS).encode())],
            )  # fmt: skip
            return
        await self.app(scope, receive, send)


async def _reply(
    send: Send,
    status: int,
    error: str,
    message: str,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body: dict[str, Any] = {"error": error, "message": message}
    payload = json.dumps(body).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(payload)).encode()),
        *(extra_headers or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
