"""Build the MCP Apps cards into apps/mcp_server/ui/dist/."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.mcp_server.ui_build import MAX_CARD_BYTES, stale_cards, write_dist


class Command(BaseCommand):
    help = "Compose each card into one self-contained HTML file; --check fails if dist is stale."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--check", action="store_true")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["check"]:
            stale = stale_cards()
            if stale:
                raise CommandError(f"Stale cards: {', '.join(stale)}. Run manage.py build_ui.")
            self.stdout.write(self.style.SUCCESS("All cards are up to date."))
            return
        for path in write_dist():
            size = path.stat().st_size
            if size > MAX_CARD_BYTES:
                raise CommandError(f"{path.name} is {size} bytes; the limit is {MAX_CARD_BYTES}.")
            self.stdout.write(f"{path.name}: {size} bytes")
        self.stdout.write(self.style.SUCCESS("Cards built."))
