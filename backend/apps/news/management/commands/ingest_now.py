"""Operator command for an explicit, policy-gated RSS ingestion attempt."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.news.models import SourceFeed
from apps.news.services import IngestResult, fetch_source


class Command(BaseCommand):
    help = "Ingest eligible RSS feeds, optionally one exact source name."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--feed", help="Exact SourceFeed name")

    def handle(self, *args: Any, **options: Any) -> None:
        feeds = SourceFeed.objects.all().order_by("name")
        if name := options.get("feed"):
            feeds = feeds.filter(name=name)
            if not feeds.exists():
                raise CommandError(f"No feed named {name!r}.")
        total = IngestResult()
        for source in feeds:
            result = fetch_source(source)
            total = IngestResult(
                new=total.new + result.new,
                duplicate=total.duplicate + result.duplicate,
                error=total.error + result.error,
                skipped=total.skipped + result.skipped,
                not_modified=total.not_modified + result.not_modified,
            )
            self.stdout.write(
                f"{source.name}: new={result.new} duplicate={result.duplicate} "
                f"error={result.error} skipped={result.skipped} not_modified={result.not_modified}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Totals: new={total.new} duplicate={total.duplicate} error={total.error} "
                f"skipped={total.skipped} not_modified={total.not_modified}"
            )
        )
