"""Retell each friction-log entry as a demo story, through the editorial pipeline."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.stories.friction import tell_friction_log


class Command(BaseCommand):
    help = "Make a demo story of every entry in docs/FRICTION_LOG.md not yet told."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--replace", action="store_true", help="Retell entries that were told before."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        for title, outcome in tell_friction_log(replace=options["replace"]).items():
            self.stdout.write(f"{title}\n  {outcome}")
