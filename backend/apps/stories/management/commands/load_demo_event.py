"""Load a hand-curated event and its tellings; the view layer for apps.stories.curated."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.stories.curated import CuratedEventError, load_curated_event, parse_curated_event


class Command(BaseCommand):
    help = "Validate and load one curated event YAML file atomically."

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path)
        parser.add_argument(
            "--synthetic", action="store_true", help="Mark the story as a test fixture."
        )
        parser.add_argument(
            "--replace", action="store_true", help="Reload an event that was loaded before."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise CommandError(f"Could not read {path}: {error}") from error
        try:
            event = parse_curated_event(text)
            result = load_curated_event(
                event, synthetic=options["synthetic"], replace=options["replace"]
            )
        except CuratedEventError as error:
            problems = "\n".join(f"  - {problem}" for problem in error.report.errors)
            raise CommandError(
                f"{path} was not loaded ({len(error.report.errors)} problem(s)); "
                f"nothing was written.\n{problems}"
            ) from error
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"Warning: {warning}"))
        story = result.story
        tones = ", ".join(story.tellings.values_list("tone", flat=True))
        self.stdout.write(
            self.style.SUCCESS(f"Loaded {story.pk} ({story.handle}); published tellings: {tones}.")
        )
