"""Give stories published before context and perspectives existed those two layers."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.stories.pipeline import add_missing_layers


class Command(BaseCommand):
    help = "Read each older story's article again and add its context and perspectives."

    def handle(self, *args: Any, **options: Any) -> None:
        outcome = add_missing_layers()
        for story_id, added in outcome.items():
            self.stdout.write(f"{story_id}: {added}")
        self.stdout.write(f"{len(outcome)} stories looked at.")
