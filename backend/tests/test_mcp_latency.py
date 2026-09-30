"""Alexa+ asks for replies under 500 ms. Measure p95 per tool with 50 stories loaded."""

from __future__ import annotations

import statistics
import time

import pytest
from apps.stories.models import Story
from mcp import Client

from tests.story_builders import many_stories
from tests.test_mcp_server import debug_mode, run_client  # noqa: F401  (autouse fixture)

pytestmark = pytest.mark.django_db

CALLS_PER_TOOL = 20
P95_LIMIT_SECONDS = 0.5


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1]


def test_every_required_tool_answers_within_500_ms_at_p95() -> None:
    stories: list[Story] = many_stories(50, topic="market day")
    target = stories[0].pk
    calls = {
        "search_events": {"query": "market day"},
        "get_briefing": {},
        "tell_tale": {"story_id": target, "beat": 1},
        "get_moral": {"story_id": target},
        "explain_proverb": {"story_id": target},
        "get_facts": {"story_id": target},
        "get_context": {"story_id": target},
        "get_perspectives": {"story_id": target},
        "get_sources": {"story_id": target},
        "save_for_later": {"story_id": target},
        "get_saved_stories": {},
        "set_preferences": {"tone": "balanced"},
    }

    async def measure(client: Client) -> dict[str, list[float]]:
        timings: dict[str, list[float]] = {}
        for name, arguments in calls.items():
            await client.call_tool(name, arguments)  # warm-up
            samples = []
            for _ in range(CALLS_PER_TOOL):
                started = time.perf_counter()
                result = await client.call_tool(name, arguments)
                samples.append(time.perf_counter() - started)
                assert not result.is_error, (name, result.content)
            timings[name] = samples
        return timings

    timings = run_client(measure)

    slow = {name: round(p95(samples), 3) for name, samples in timings.items()}
    print("\np95 seconds per tool:", slow)
    assert all(value < P95_LIMIT_SECONDS for value in slow.values()), slow
