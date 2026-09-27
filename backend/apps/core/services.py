"""Small health-check services kept separate from HTTP views."""

from __future__ import annotations

from typing import TypedDict

import redis
from django.conf import settings
from django.db import connections


class DependencyStatus(TypedDict):
    status: str


class HealthReport(TypedDict):
    status: str
    database: DependencyStatus
    redis: DependencyStatus


def database_status() -> DependencyStatus:
    """Check the database with a minimal query rather than trusting configuration."""
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # Health responses intentionally avoid internal details.
        return {"status": "unavailable"}
    return {"status": "ok"}


def redis_status() -> DependencyStatus:
    """Check Redis directly because Celery needs a reachable broker, not a cache stub."""
    try:
        redis.Redis.from_url(settings.REDIS_URL).ping()
    except redis.RedisError:
        return {"status": "unavailable"}
    return {"status": "ok"}


def get_health_report() -> HealthReport:
    """Return the dependency state used by the web health endpoint."""
    database = database_status()
    redis_dependency = redis_status()
    dependencies_are_healthy = database["status"] == redis_dependency["status"] == "ok"
    overall_status = "ok" if dependencies_are_healthy else "unavailable"
    return {"status": overall_status, "database": database, "redis": redis_dependency}
