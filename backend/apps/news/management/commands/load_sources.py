"""Load owner-reviewed RSS source records from a YAML file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.news.models import SourceFeed

REQUIRED_FIELDS = {
    "name",
    "feed_url",
    "region",
    "language",
    "terms_url",
    "terms_reviewed_at",
    "use_policy",
    "attribution_text",
    "active",
    "min_interval_minutes",
}


class Command(BaseCommand):
    help = "Load approved RSS source records from YAML without fetching them."

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path)

    def handle(self, *args: Any, **options: Any) -> None:
        path: Path = options["path"]
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise CommandError(f"Could not read {path}: {error}") from error
        rows = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise CommandError("YAML must contain a top-level sources list.")

        with transaction.atomic():
            prepared = [prepare_row(row, index) for index, row in enumerate(rows, start=1)]
            created = updated = 0
            for row in prepared:
                existing = SourceFeed.objects.filter(feed_url=row["feed_url"]).first()
                feed = existing or SourceFeed()
                for field, value in row.items():
                    setattr(feed, field, value)
                feed.full_clean()
                feed.save()
                if existing:
                    updated += 1
                else:
                    created += 1
        self.stdout.write(
            self.style.SUCCESS(f"Sources loaded: created={created} updated={updated}")
        )


def prepare_row(row: object, index: int) -> dict[str, object]:
    """Validate the full SourceFeed surface before transaction writes begin."""
    if not isinstance(row, dict):
        raise CommandError(f"sources[{index}] must be a mapping.")
    missing = REQUIRED_FIELDS - row.keys()
    if missing:
        raise CommandError(f"sources[{index}] is missing: {', '.join(sorted(missing))}")
    prepared = {field: row[field] for field in REQUIRED_FIELDS}
    value = prepared["terms_reviewed_at"]
    if isinstance(value, str):
        parsed = parse_datetime(value.replace("Z", "+00:00"))
        if parsed is None:
            raise CommandError(f"sources[{index}].terms_reviewed_at must be ISO-8601.")
        prepared["terms_reviewed_at"] = parsed
    elif not isinstance(value, datetime):
        raise CommandError(f"sources[{index}].terms_reviewed_at must be a datetime.")
    return prepared
