"""The MCP server over real Streamable HTTP, driven by the official SDK client, in-process."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
import yaml
from apps.mcp_server.server import create_app
from apps.memory.models import StoryEncounter
from apps.stories.curated import CuratedEvent, load_curated_event
from apps.stories.models import Story
from apps.wisdom.models import Proverb
from asgiref.sync import async_to_sync
from django.conf import settings
from django.test import override_settings
from jsonschema import Draft202012Validator
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from tests.factories import ProverbFactory

pytestmark = pytest.mark.django_db

BASE = "http://localhost:8001"
FIXTURE = Path(settings.BASE_DIR).parent / "data" / "demo_event.synthetic.yaml"
TOOL_NAMES = {
    "search_events",
    "get_briefing",
    "tell_tale",
    "get_moral",
    "explain_proverb",
    "get_facts",
    "get_context",
    "get_perspectives",
    "get_sources",
}
FORBIDDEN_IN_SPEECH = ("story_id", "json", "exception", "traceback", "validation", "st_")


@pytest.fixture(autouse=True)
def debug_mode(settings) -> None:
    """pytest-django runs with DEBUG off; the dev identity header needs it on, as locally."""
    settings.DEBUG = True


@pytest.fixture
def story() -> Story:
    ProverbFactory(id="pv_synthetic01", spoken_form="Test proverb one is spoken here.")
    ProverbFactory(
        id="pv_synthetic02", spoken_form="Test proverb two is spoken here.", culture="Hausa"
    )
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    return load_curated_event(CuratedEvent.model_validate(data), synthetic=True).story


def run_client(work: Callable[[Client], Awaitable[Any]], *, user: str | None = "listener-1") -> Any:
    """Start the app's lifespan, connect the SDK client over HTTP, and run `work`."""

    async def main() -> Any:
        app = create_app()
        headers = {"X-Greeo-User": user} if user else {}
        async with app.router.lifespan_context(app):
            http = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers
            )
            async with (
                http,
                Client(
                    streamable_http_client(f"{BASE}/mcp", http_client=http), mode="legacy"
                ) as client,
            ):
                return await work(client)

    return async_to_sync(main)()


def call(name: str, arguments: dict[str, Any], **kwargs: Any):
    return run_client(lambda client: client.call_tool(name, arguments), **kwargs)


def spoken(result) -> str:
    return " ".join(block.text for block in result.content)


def assert_voice_safe(result) -> None:
    text = spoken(result).lower()
    assert text.strip()
    assert not [word for word in FORBIDDEN_IN_SPEECH if word in text], text


def raw_post(body: dict, headers: dict[str, str]) -> httpx2.Response:
    async def main() -> httpx2.Response:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=BASE
            ) as http:
                return await http.post("/mcp", json=body, headers=headers)

    return async_to_sync(main)()


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "greeo-tests", "version": "1"},
    },
}
GOOD_HEADERS = {"Accept": "application/json, text/event-stream"}


# Protocol and transport -------------------------------------------------------------------


def test_tool_list_has_all_nine_tools_with_valid_schemas() -> None:
    tools = run_client(lambda client: client.list_tools()).tools

    assert {tool.name for tool in tools} == TOOL_NAMES
    for tool in tools:
        Draft202012Validator.check_schema(tool.input_schema)
        Draft202012Validator.check_schema(tool.output_schema)
        assert "spoken" in tool.output_schema["properties"]
        assert "read aloud" in tool.description
        assert "ctx" not in tool.input_schema.get("properties", {})


def test_initialize_negotiates_2025_11_25_with_json_response() -> None:
    response = raw_post(INITIALIZE, GOOD_HEADERS)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["result"]["protocolVersion"] == "2025-11-25"
    assert "mcp-session-id" not in response.headers  # stateless


def test_bad_origin_is_rejected_with_403() -> None:
    response = raw_post(INITIALIZE, {**GOOD_HEADERS, "Origin": "https://evil.example"})

    assert response.status_code == 403


def test_allowed_origin_is_accepted() -> None:
    response = raw_post(INITIALIZE, {**GOOD_HEADERS, "Origin": "http://localhost:5173"})

    assert response.status_code == 200


def test_accept_header_without_json_is_rejected_with_406() -> None:
    response = raw_post(INITIALIZE, {"Accept": "text/html"})

    assert response.status_code == 406


def test_health_route_reports_dependencies() -> None:
    async def main() -> httpx2.Response:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=BASE
            ) as http:
                return await http.get("/healthz")

    response = async_to_sync(main)()

    assert response.status_code in (200, 503)
    assert set(response.json()) == {"status", "database", "redis"}


# Finding stories --------------------------------------------------------------------------


def test_search_finds_the_seeded_event(story: Story) -> None:
    result = call("search_events", {"query": "footbridge Veloria"})

    assert not result.is_error
    assert result.structured_content["stories"][0]["story_id"] == story.pk
    assert_voice_safe(result)


def test_search_with_no_match_suggests_an_alternative(story: Story) -> None:
    result = call("search_events", {"query": "volcano"})

    assert result.is_error
    assert result.structured_content["error"] == "no_results"
    assert "today's stories" in result.structured_content["next_options"]
    assert_voice_safe(result)


def test_briefing_lists_recent_stories_and_filters_by_region(story: Story) -> None:
    result = call("get_briefing", {})
    missing = call("get_briefing", {"region": "Atlantis"})

    assert [s["story_id"] for s in result.structured_content["stories"]] == [story.pk]
    assert missing.is_error and missing.structured_content["error"] == "no_results"


# The tale -----------------------------------------------------------------------------------


def test_tale_is_told_one_beat_at_a_time_until_has_more_is_false(story: Story) -> None:
    async def listen(client: Client) -> list:
        return [
            await client.call_tool("tell_tale", {"story_id": story.pk, "beat": beat})
            for beat in (1, 2, 3)
        ]

    beats = run_client(listen)

    assert [b.structured_content["has_more"] for b in beats] == [True, True, False]
    assert all(b.structured_content["beats_total"] == 3 for b in beats)
    first = beats[0].structured_content
    assert "Test proverb one is spoken here." in first["text"]
    assert "{{" not in first["text"]
    assert spoken(beats[0]) == first["text"]
    assert first["proverbs_used"][0]["culture"] == "Test culture"
    assert "the reflection" in beats[-1].structured_content["next_options"]
    for beat in beats:
        assert_voice_safe(beat)


def test_tale_records_progress_for_the_dev_header_user(story: Story) -> None:
    call("tell_tale", {"story_id": story.pk, "beat": 2}, user="listener-7")

    encounter = StoryEncounter.objects.get(user__external_id="dev:listener-7", story=story)
    assert (encounter.last_beat, encounter.tone_heard) == (2, "balanced")


def test_guests_hear_the_tale_but_nothing_is_recorded(story: Story) -> None:
    result = call("tell_tale", {"story_id": story.pk}, user=None)

    assert not result.is_error
    assert not StoryEncounter.objects.exists()


def test_dev_header_is_ignored_outside_debug(story: Story) -> None:
    with override_settings(DEBUG=False):
        call("tell_tale", {"story_id": story.pk}, user="listener-9")

    assert not StoryEncounter.objects.exists()


def test_unavailable_tone_falls_back_and_reports_tone_served(story: Story) -> None:
    result = call("tell_tale", {"story_id": story.pk, "tone": "light"})

    assert not result.is_error
    assert result.structured_content["tone_served"] == "balanced"


def test_requested_tone_is_served_when_available(story: Story) -> None:
    result = call("tell_tale", {"story_id": story.pk, "tone": "serious"})

    assert result.structured_content["tone_served"] == "serious"


def test_beat_out_of_range_is_a_friendly_error(story: Story) -> None:
    result = call("tell_tale", {"story_id": story.pk, "beat": 9})

    assert result.is_error
    assert result.structured_content["error"] == "beat_out_of_range"
    assert "3 parts" in spoken(result)
    assert_voice_safe(result)


def test_disputed_proverb_falls_back_to_another_tone_or_a_friendly_error(story: Story) -> None:
    Proverb.objects.filter(pk="pv_synthetic01").update(
        verification_status=Proverb.VerificationStatus.DISPUTED
    )

    result = call("tell_tale", {"story_id": story.pk, "beat": 1})

    # Both tellings use P1 in beat 1, so nothing safe remains: never speak it.
    assert result.is_error
    assert result.structured_content["error"] == "tale_unavailable"
    assert "Test proverb one" not in spoken(result)


def test_unknown_story_is_a_friendly_error() -> None:
    result = call("tell_tale", {"story_id": "st_doesnotexist"})

    assert result.is_error
    assert result.structured_content["error"] == "unknown_story"
    assert_voice_safe(result)


def test_invalid_arguments_are_rewritten_in_plain_words(story: Story) -> None:
    result = call("tell_tale", {"story_id": story.pk, "beat": 0})
    malformed = call("get_facts", {"story_id": "not an id"})

    for bad in (result, malformed):
        assert bad.is_error
        assert bad.structured_content["error"] == "invalid_request"
        assert_voice_safe(bad)


def test_synthetic_stories_are_hidden_when_not_allowed(story: Story) -> None:
    with override_settings(ALLOW_SYNTHETIC=False):
        result = call("tell_tale", {"story_id": story.pk})

    assert result.is_error and result.structured_content["error"] == "unknown_story"


# Truth layers -------------------------------------------------------------------------------


def test_moral_returns_the_reflection_and_proverb_note(story: Story) -> None:
    result = call("get_moral", {"story_id": story.pk})

    content = result.structured_content
    assert content["closing_kind"] == "reflection"
    assert content["text"] == "A crossing built together is carried together."
    assert content["proverb_note"] == "The tale carried a proverb from the Test culture people."


def test_explain_proverb_gives_culture_meaning_original_and_source(story: Story) -> None:
    first = call("explain_proverb", {"story_id": story.pk})
    second = call("explain_proverb", {"story_id": story.pk, "which": 2})
    missing = call("explain_proverb", {"story_id": story.pk, "which": 3})

    assert first.structured_content["original_text"].startswith("TEST PROVERB")
    assert first.structured_content["source_citation"] == "Synthetic source one"
    assert spoken(second).startswith("This proverb comes from the Hausa people")
    assert missing.is_error and missing.structured_content["error"] == "proverb_out_of_range"


def test_facts_include_publishers_and_dates(story: Story) -> None:
    result = call("get_facts", {"story_id": story.pk})

    facts = result.structured_content["facts"]
    assert len(facts) == 3
    assert facts[0]["sources"][0] == {"publisher": "Synthetic Gazette", "date": "12 March 2026"}
    assert "Reported by Synthetic Gazette and Synthetic Courier." in spoken(result)
    assert_voice_safe(result)


def test_context_and_perspectives(story: Story) -> None:
    context = call("get_context", {"story_id": story.pk})
    perspectives = call("get_perspectives", {"story_id": story.pk})

    assert context.structured_content["context"][0]["label"] == "Some background"
    labels = [p["label"] for p in perspectives.structured_content["perspectives"]]
    assert labels == ["Bridge committee", "Canoe operators"]


def test_sources_are_deduplicated_and_links_are_off_by_default(story: Story) -> None:
    result = call("get_sources", {"story_id": story.pk})

    sources = result.structured_content["sources"]
    assert len(sources) == 2
    gazette = next(s for s in sources if s["publisher"] == "Synthetic Gazette")
    assert gazette["supports"] == ["facts", "perspectives"]
    assert all(s["url"] is None for s in sources)
    assert "http" not in spoken(result)


def test_source_links_appear_only_when_enabled(story: Story) -> None:
    with override_settings(INCLUDE_SOURCE_URLS=True):
        result = call("get_sources", {"story_id": story.pk})

    urls = [s["url"] for s in result.structured_content["sources"]]
    assert all(url and url.startswith("https://") and "utm_" not in url for url in urls)
    assert "http" not in spoken(result)


def test_facts_mid_tale_keep_progress_and_suggest_continuing(story: Story) -> None:
    async def flow(client: Client):
        await client.call_tool("tell_tale", {"story_id": story.pk, "beat": 1})
        return await client.call_tool("get_facts", {"story_id": story.pk})

    facts = run_client(flow)

    assert facts.structured_content["next_options"][0] == "continue at beat 2"
    encounter = StoryEncounter.objects.get(story=story)
    assert encounter.last_beat == 1 and "facts" in encounter.layers_explored


def test_layer_tools_never_suggest_the_layer_just_heard(story: Story) -> None:
    async def flow(client: Client) -> dict:
        for beat in (1, 2, 3):
            await client.call_tool("tell_tale", {"story_id": story.pk, "beat": beat})
        results = {}
        for tool, label in (
            ("get_moral", "the reflection"),
            ("explain_proverb", "the proverb explained"),
            ("get_facts", "the facts"),
            ("get_context", "the background"),
            ("get_perspectives", "different perspectives"),
            ("get_sources", "the sources"),
        ):
            result = await client.call_tool(tool, {"story_id": story.pk})
            results[label] = result.structured_content["next_options"]
        return results

    results = run_client(flow)
    for label, next_options in results.items():
        assert label not in next_options, (label, next_options)
        assert len(next_options) == len(set(next_options))
    # By the end every layer has been heard, so no layer is offered again.
    assert results["the sources"] == ["another story"]
