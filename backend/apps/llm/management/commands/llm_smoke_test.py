"""Verify the configured gateway without invoking editorial workflow code."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from pydantic import BaseModel

from apps.llm.client import generate_json
from apps.llm.exceptions import LLMError


class SmokeResponse(BaseModel):
    facts: list[str]
    synthetic: bool


class Command(BaseCommand):
    help = "Call the configured LLM gateway with a harmless schema validation check."

    def handle(self, *args, **options) -> None:
        try:
            response = generate_json(
                "establish_facts",
                {"pipeline_run_id": "llm-smoke-test", "fixture": "SYNTHETIC EVENT"},
                SmokeResponse,
            )
        except LLMError as error:
            raise CommandError(f"LLM smoke test failed: {error}") from error
        self.stdout.write(self.style.SUCCESS(f"LLM smoke test passed: {response.model_dump()}"))
