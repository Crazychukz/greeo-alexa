"""Run the editorial pipeline once: recent articles in, published stories out."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.stories.pipeline import run_pipeline


class Command(BaseCommand):
    help = "Turn up to --limit recent, untold articles into published Greeo stories."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--limit", type=int, default=3)
        parser.add_argument("--since-hours", type=int, default=48)

    def handle(self, *args: Any, **options: Any) -> None:
        result = run_pipeline(options["limit"], since_hours=options["since_hours"])
        for story_id in result.published:
            self.stdout.write(self.style.SUCCESS(f"published {story_id}"))
        for url, reasons in result.rejected.items():
            self.stdout.write(self.style.WARNING(f"not published: {url}"))
            for reason in reasons[:5]:
                self.stdout.write(f"  - {reason}")
        self.stdout.write(f"Run {result.run_id}: {len(result.published)} published, "
                          f"{len(result.rejected)} not published.")  # fmt: skip
