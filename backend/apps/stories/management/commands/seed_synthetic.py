"""Seed a visibly synthetic event for local development and demos of the plumbing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.wisdom.models import Proverb

# Fixed ids so the synthetic YAML can reference them; real proverbs get random ids.
SYNTHETIC_PROVERBS = {
    "pv_synthetic01": ("TEST PROVERB 1", "Test proverb one is spoken here."),
    "pv_synthetic02": ("TEST PROVERB 2", "Test proverb two is spoken here."),
}
FIXTURE = Path(settings.BASE_DIR).parent / "data" / "demo_event.synthetic.yaml"


class Command(BaseCommand):
    help = "Create synthetic proverbs and load the synthetic curated event (dev only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.ALLOW_SYNTHETIC:
            raise CommandError("ALLOW_SYNTHETIC is off; synthetic data is not seeded here.")
        for proverb_id, (original, spoken) in SYNTHETIC_PROVERBS.items():
            Proverb.objects.update_or_create(
                id=proverb_id,
                defaults={
                    "original_text": original,
                    "language": "Synthetic language",
                    "spoken_form": spoken,
                    "translation": spoken,
                    "meaning_note": "SYNTHETIC meaning note for testing only.",
                    "culture": "Synthetic culture",
                    "region": "Synthetic region",
                    "source_citation": "Synthetic citation one",
                    "second_source_citation": "Synthetic citation two",
                    "license": "Synthetic test data",
                    "verification_status": Proverb.VerificationStatus.VERIFIED,
                    "themes": ["cooperation", "resilience"],
                    "tone_ok": True,
                },
            )
        call_command("load_demo_event", FIXTURE, synthetic=True, replace=True, stdout=self.stdout)
