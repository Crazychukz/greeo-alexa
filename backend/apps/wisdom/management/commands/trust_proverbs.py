"""Mark imported proverbs as approved for use, by the owner's decision.

Imports arrive with tone_ok false so that a person decides. This command records that
decision for the whole corpus at once. It changes nothing else: sources and citations
stay, and single-source entries are still served only while
DEMO_ALLOW_SINGLE_SOURCE_PROVERBS is on (see docs/proverbs/DEMO_CORPUS.md).
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.wisdom.models import Proverb


class Command(BaseCommand):
    help = "Approve every imported proverb for use (tone_ok), or undo with --undo."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--undo", action="store_true", help="Set tone_ok back to false.")

    def handle(self, *args: Any, **options: Any) -> None:
        trusted = not options["undo"]
        changed = Proverb.objects.exclude(tone_ok=trusted).update(tone_ok=trusted)
        servable = Proverb.objects.servable().count()
        self.stdout.write(
            self.style.SUCCESS(
                f"{'Approved' if trusted else 'Un-approved'} {changed} proverbs. "
                f"Servable now: {servable} of {Proverb.objects.count()}."
            )
        )
        if trusted and servable < Proverb.objects.filter(tone_ok=True).count():
            self.stdout.write(
                "Single-source proverbs need DEMO_ALLOW_SINGLE_SOURCE_PROVERBS=true to be served."
            )
