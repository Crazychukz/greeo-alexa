"""Safe queryset for material that may be spoken to users."""

from django.conf import settings
from django.db import models


def servable_statuses() -> tuple[str, ...]:
    """Verified only, unless the documented demo switch also admits single-source entries.

    This is the one place the rule lives, so publication, rendering and retrieval agree.
    See docs/proverbs/DEMO_CORPUS.md before turning the switch on.
    """
    if getattr(settings, "DEMO_ALLOW_SINGLE_SOURCE_PROVERBS", False):
        return ("verified", "single_source")
    return ("verified",)


class ProverbQuerySet(models.QuerySet):
    def servable(self) -> "ProverbQuerySet":
        return self.filter(verification_status__in=servable_statuses(), tone_ok=True)


class ProverbManager(models.Manager.from_queryset(ProverbQuerySet)):
    pass
