"""Create a demo listener and print a bearer token for them, once."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from apps.memory.services import get_or_create_user
from apps.memory.tokens import issue_token, revoke_tokens


class Command(BaseCommand):
    help = "Create (or reuse) a demo listener and print a new bearer token. Shown once only."

    def add_arguments(self, parser) -> None:
        parser.add_argument("name", help="A short name, for example judge-1.")
        parser.add_argument("--label", default="", help="What this token is for.")
        parser.add_argument(
            "--revoke-existing", action="store_true", help="Revoke this user's older tokens."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        name = options["name"].strip()
        if not name or len(name) > 100 or not name.replace("-", "").replace("_", "").isalnum():
            raise CommandError("Use a short name of letters, digits, - or _.")
        user = get_or_create_user(f"demo:{name}")
        if options["revoke_existing"]:
            revoked = revoke_tokens(user)
            self.stdout.write(f"Revoked {revoked} older token(s).")
        token = issue_token(user, label=options["label"] or name)
        self.stdout.write(self.style.SUCCESS(f"Demo listener: {user.external_id}"))
        self.stdout.write(f"Bearer token (shown once, store it now): {token}")
        self.stdout.write("Send it as:  Authorization: Bearer <token>")
        self.stdout.write("This is a demo token, not Alexa+ account linking.")
