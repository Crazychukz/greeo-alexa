"""Querysets that protect story visibility invariants."""

from django.conf import settings
from django.db import models


class StoryQuerySet(models.QuerySet):
    def listable(self) -> "StoryQuerySet":
        """Hide synthetic data except in explicitly enabled development/test environments."""
        if getattr(settings, "ALLOW_SYNTHETIC", False):
            return self
        return self.filter(is_synthetic=False)


class StoryManager(models.Manager.from_queryset(StoryQuerySet)):
    pass
