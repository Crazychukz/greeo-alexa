"""Safe queryset for material that may be spoken to users."""

from django.db import models


class ProverbQuerySet(models.QuerySet):
    def servable(self) -> "ProverbQuerySet":
        return self.filter(verification_status="verified", tone_ok=True)


class ProverbManager(models.Manager.from_queryset(ProverbQuerySet)):
    pass
