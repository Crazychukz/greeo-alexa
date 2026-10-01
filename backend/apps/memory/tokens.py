"""Demo bearer tokens: issue, look up and revoke. Only hashes ever touch the database.

A token is 32 random bytes, so a plain SHA-256 hash is enough: there is nothing to
brute-force, unlike a human-chosen password, and a fast hash keeps every tool call quick.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from django.utils import timezone

from .models import ApiToken, EndUser

TOKEN_PREFIX = "greeo_"
LAST_USED_RESOLUTION = timedelta(minutes=1)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(user: EndUser, label: str = "") -> str:
    """Create a token and return it. This is the only time the token itself exists."""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    ApiToken.objects.create(user=user, token_hash=hash_token(token), label=label)
    return token


def user_for_token(token: str) -> EndUser | None:
    """The user behind a live token, or None if it is unknown or revoked."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    record = (
        ApiToken.objects.select_related("user")
        .filter(token_hash=hash_token(token), revoked=False)
        .first()
    )
    if record is None:
        return None
    now = timezone.now()
    # Note when the token was used, without a database write on every single call.
    if record.last_used_at is None or now - record.last_used_at > LAST_USED_RESOLUTION:
        ApiToken.objects.filter(pk=record.pk).update(last_used_at=now)
    return record.user


def revoke_tokens(user: EndUser) -> int:
    return ApiToken.objects.filter(user=user, revoked=False).update(revoked=True)
