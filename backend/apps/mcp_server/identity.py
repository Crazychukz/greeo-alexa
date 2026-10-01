"""Who is calling. Identity comes from the request, never from a tool argument.

Three kinds of caller:
- a demo bearer token (`Authorization: Bearer greeo_...`), for the simulator and judges;
- the development header `X-Greeo-User`, only when DEBUG and MCP_ALLOW_DEV_IDENTITY are on;
- a guest, who can hear every story but has no memory.

None of this is Alexa+ production authentication. In production the bearer token is an
OAuth 2.1 access token from account linking, validated for this server as its audience;
that design is in docs/ALEXA_ACCOUNT_LINKING.md and is not implemented here.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from apps.memory.models import EndUser
from apps.memory.services import get_or_create_user
from apps.memory.tokens import user_for_token

DEV_USER_HEADER = "x-greeo-user"
BEARER = "bearer "


def dev_identity_enabled() -> bool:
    return bool(settings.DEBUG and settings.MCP_ALLOW_DEV_IDENTITY)


def assert_safe_identity_settings() -> None:
    """Refuse to start if the development header would be trusted outside DEBUG."""
    if settings.MCP_ALLOW_DEV_IDENTITY and not settings.DEBUG:
        raise ImproperlyConfigured(
            "MCP_ALLOW_DEV_IDENTITY is on while DEBUG is off. The X-Greeo-User header lets "
            "anyone claim any identity, so it is only allowed in development. Set "
            "MCP_ALLOW_DEV_IDENTITY=false, or DJANGO_DEBUG=true for local work."
        )


def bearer_token(headers: Mapping[str, str] | None) -> str | None:
    """The token from an Authorization: Bearer header, if one was sent."""
    value = _lowered(headers).get("authorization", "").strip()
    if value[: len(BEARER)].lower() != BEARER:
        return None
    return value[len(BEARER) :].strip() or None


def current_user(headers: Mapping[str, str] | None) -> EndUser | None:
    """Return the listener for this request, or None for a guest."""
    token = bearer_token(headers)
    if token:
        # The HTTP gate has already rejected unknown tokens with a 401.
        return user_for_token(token)
    if dev_identity_enabled():
        dev_user = _lowered(headers).get(DEV_USER_HEADER, "").strip()
        if dev_user:
            return get_or_create_user(f"dev:{dev_user[:200]}")
    return None


def _lowered(headers: Mapping[str, str] | None) -> dict[str, str]:
    return {key.lower(): value for key, value in (headers or {}).items()}
