"""Redis-backed limits that stop accidental runaway editorial runs."""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Protocol

import redis
from django.conf import settings

from .exceptions import BudgetExceeded


class BudgetGuard(Protocol):
    """The small interface the gateway needs, allowing deterministic tests."""

    def reserve(self, run_id: str, prompt: str, max_tokens: int) -> int: ...

    def settle(self, reservation: int, actual_tokens: int) -> None: ...


class RedisBudgetGuard:
    """Reserve a conservative token amount before each provider request."""

    def __init__(self, client: redis.Redis | None = None) -> None:
        self.client = client or redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    def reserve(self, run_id: str, prompt: str, max_tokens: int) -> int:
        """Atomically count a call and reserve input plus maximum output tokens."""
        call_key = f"greeo:llm:calls:{run_id}"
        calls = self._incr_with_expiry(call_key, 1, 86400)
        if calls > settings.LLM_MAX_CALLS_PER_RUN:
            self.client.decr(call_key)
            raise BudgetExceeded(
                f"LLM_MAX_CALLS_PER_RUN ({settings.LLM_MAX_CALLS_PER_RUN}) exceeded for {run_id}."
            )

        reservation = ceil(len(prompt) / 4) + max_tokens
        day = datetime.now(UTC).date().isoformat()
        token_key = f"greeo:llm:tokens:{day}"
        used = self._incr_with_expiry(token_key, reservation, 172800)
        if used > settings.LLM_DAILY_TOKEN_BUDGET:
            self.client.decrby(token_key, reservation)
            self.client.decr(call_key)
            raise BudgetExceeded(
                f"LLM_DAILY_TOKEN_BUDGET ({settings.LLM_DAILY_TOKEN_BUDGET}) would be exceeded."
            )
        return reservation

    def settle(self, reservation: int, actual_tokens: int) -> None:
        """Replace a conservative reservation with observed provider usage.

        A failed call settles with zero tokens so its reservation is returned.
        """
        day = datetime.now(UTC).date().isoformat()
        self.client.incrby(f"greeo:llm:tokens:{day}", actual_tokens - reservation)

    def _incr_with_expiry(self, key: str, amount: int, ttl_seconds: int) -> int:
        """Increment and set expiry in one transaction so a key never outlives its window."""
        pipeline = self.client.pipeline(transaction=True)
        pipeline.incrby(key, amount)
        pipeline.expire(key, ttl_seconds)
        value, _ = pipeline.execute()
        return int(value)
