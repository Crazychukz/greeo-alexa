"""Who is calling. Identity comes from the request, never from a tool argument.

Production identity is the account-linking bearer token (Phase 11). Until then, story
tools work for everyone as a guest experience, and in DEBUG only a development header
names the listener so memory can be exercised locally and by the simulator.
"""

from __future__ import annotations

from collections.abc import Mapping

from django.conf import settings

from apps.memory.models import EndUser
from apps.memory.services import get_or_create_user

DEV_USER_HEADER = "x-greeo-user"


def current_user(headers: Mapping[str, str] | None) -> EndUser | None:
    """Return the listener for this request, or None for a guest."""
    if not headers:
        return None
    lowered = {key.lower(): value for key, value in headers.items()}
    if settings.DEBUG:
        dev_user = lowered.get(DEV_USER_HEADER, "").strip()
        if dev_user:
            return get_or_create_user(f"dev:{dev_user[:200]}")
    # Bearer tokens are verified in Phase 11; until then an unverified token is a guest.
    return None
