"""Import a reviewed proverb corpus atomically from JSON Lines."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.wisdom.models import Proverb
from apps.wisdom.themes import validate_theme_keys

REQUIRED_FIELDS = {
    "original_text",
    "language",
    "spoken_form",
    "translation",
    "meaning_note",
    "speak_original_ok",
    "culture",
    "region",
    "source_citation",
    "second_source_citation",
    "license",
    "verification_status",
    "dispute_note",
    "themes",
    "tone_ok",
}
GENERIC_CULTURES = {"africa", "african"}


def normalized_key(entry: dict[str, object]) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", str(entry["original_text"]).casefold()).strip()
    return text, str(entry["culture"]).casefold().strip()


def validate_entries(entries: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Validate every line before any write to keep corpus imports atomic."""
    validated: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for line_number, entry in enumerate(entries, start=1):
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            raise CommandError(
                f"Line {line_number}: missing field(s): {', '.join(sorted(missing))}."
            )
        unknown = entry.keys() - REQUIRED_FIELDS
        if unknown:
            raise CommandError(
                f"Line {line_number}: unknown field(s): {', '.join(sorted(unknown))}."
            )
        if not isinstance(entry["themes"], list) or not all(
            isinstance(theme, str) for theme in entry["themes"]
        ):
            raise CommandError(f"Line {line_number}: themes must be a list of strings.")
        try:
            validate_theme_keys(entry["themes"])
        except ValueError as exc:
            raise CommandError(f"Line {line_number}: {exc}") from exc
        if str(entry["culture"]).casefold().strip() in GENERIC_CULTURES:
            raise CommandError(f"Line {line_number}: culture must be specific, not African/Africa.")
        if entry["verification_status"] not in Proverb.VerificationStatus.values:
            raise CommandError(f"Line {line_number}: unknown verification_status.")
        if entry["verification_status"] == Proverb.VerificationStatus.VERIFIED and (
            not str(entry["source_citation"]).strip()
            or not str(entry["second_source_citation"]).strip()
            or not str(entry["spoken_form"]).strip()
        ):
            raise CommandError(
                f"Line {line_number}: verified entries need spoken_form and two citations."
            )
        key = normalized_key(entry)
        if key in seen:
            raise CommandError(
                f"Line {line_number}: duplicate original_text and culture in import."
            )
        seen.add(key)
        validated.append(entry)
    return validated


VERIFICATION_RANK = {
    Proverb.VerificationStatus.UNVERIFIED: 0,
    Proverb.VerificationStatus.SINGLE_SOURCE: 1,
    Proverb.VerificationStatus.VERIFIED: 2,
}


def keep_review_decisions(existing: Proverb, entry: dict[str, object]) -> dict[str, object]:
    """Stop a re-import from undoing review done in the admin.

    A file may raise verification or approve tone, and may mark an entry disputed, but it
    may not silently lower a status, clear a dispute, or withdraw a tone approval a person
    gave. When a verified entry is kept verified, its citations are kept too.
    """
    merged = dict(entry)
    if existing.tone_ok and not entry["tone_ok"]:
        merged["tone_ok"] = True
    incoming = entry["verification_status"]
    current = existing.verification_status
    if current == Proverb.VerificationStatus.DISPUTED:
        merged["verification_status"] = current
    elif incoming != Proverb.VerificationStatus.DISPUTED and VERIFICATION_RANK.get(
        current, -1
    ) > VERIFICATION_RANK.get(incoming, -1):
        merged["verification_status"] = current
        for field in ("source_citation", "second_source_citation"):
            if not str(entry[field]).strip():
                merged[field] = getattr(existing, field)
    return merged


class Command(BaseCommand):
    help = "Import a verified proverb corpus JSONL file without partial writes."

    def add_arguments(self, parser) -> None:
        parser.add_argument("path", type=Path)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options) -> None:
        path: Path = options["path"]
        try:
            entries = [
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Could not read JSONL corpus: {exc}") from exc
        validated = validate_entries(entries)
        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"Validated {len(validated)} proverb(s); no changes made.")
            )
            return
        with transaction.atomic():
            for entry in validated:
                text, culture = normalized_key(entry)
                existing = next(
                    (
                        proverb
                        for proverb in Proverb.objects.filter(culture__iexact=culture)
                        if re.sub(r"\s+", " ", proverb.original_text.casefold()).strip() == text
                    ),
                    None,
                )
                if existing:
                    for field, value in keep_review_decisions(existing, entry).items():
                        setattr(existing, field, value)
                    existing.full_clean()
                    existing.save()
                else:
                    proverb = Proverb(**entry)
                    proverb.full_clean()
                    proverb.save()
        counts = {
            status: Proverb.objects.filter(verification_status=status).count()
            for status in Proverb.VerificationStatus.values
        }
        self.stdout.write(
            self.style.SUCCESS(f"Imported {len(validated)} proverb(s). Counts: {counts}")
        )
