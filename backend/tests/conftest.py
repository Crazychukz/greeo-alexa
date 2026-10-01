"""Fixtures shared across the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from apps.memory import services as memory
from apps.stories.curated import CuratedEvent, load_curated_event
from apps.stories.models import Story
from django.conf import settings

from tests.factories import ProverbFactory

SYNTHETIC_EVENT = Path(settings.BASE_DIR).parent / "data" / "demo_event.synthetic.yaml"


class InMemoryStore:
    """A per-test stand-in for Redis session context, so tests never share state."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int) -> bool:
        self.values[key] = value
        return True

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)


@pytest.fixture(autouse=True)
def isolated_session_context(monkeypatch) -> InMemoryStore:
    """Greeo's 30-minute session context lives in memory for the length of one test."""
    store = InMemoryStore()
    monkeypatch.setattr(memory, "_default_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def safe_identity_defaults(settings) -> None:
    """pytest-django turns DEBUG off, so dev identity is off too unless a test enables both.

    The rate limiter is off by default so tests never share counters in real Redis.
    """
    settings.MCP_ALLOW_DEV_IDENTITY = False
    settings.MCP_RATE_LIMIT_PER_MINUTE = 0


@pytest.fixture(autouse=True)
def no_cloud_calls(settings, monkeypatch) -> None:
    """Tests never reach AWS, whatever the developer's .env says.

    Compose loads .env into the container that runs pytest, so a Bedrock or Polly setup
    there would otherwise make tests slow, flaky and billed. Tests that exercise those
    backends pass a fake client and set the backend themselves.
    """
    settings.LLM_BACKEND = "mock"
    settings.SPEECH_BACKEND = "mock"
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def dev_identity(settings) -> None:
    """Trust the X-Greeo-User header, as local development does."""
    settings.DEBUG = True
    settings.MCP_ALLOW_DEV_IDENTITY = True


@pytest.fixture
def story(db) -> Story:
    """The synthetic curated event, loaded through the real loader."""
    ProverbFactory(id="pv_synthetic01", spoken_form="Test proverb one is spoken here.")
    ProverbFactory(
        id="pv_synthetic02", spoken_form="Test proverb two is spoken here.", culture="Hausa"
    )
    data = yaml.safe_load(SYNTHETIC_EVENT.read_text(encoding="utf-8"))
    return load_curated_event(CuratedEvent.model_validate(data), synthetic=True).story
