"""MCP Apps cards: resources, tool links, offline-safety, freshness, and text fallback."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import httpx2
import pytest
from apps.mcp_server import ui_build
from apps.mcp_server.server import CARD_FOR_TOOL, create_app
from apps.stories.models import Story, StoryTelling
from asgiref.sync import async_to_sync
from mcp import Client
from mcp.client.extension import advertise
from mcp.client.streamable_http import streamable_http_client
from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID

from tests.test_mcp_server import BASE, debug_mode, run_client  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

CARD_URIS = {f"ui://greeo/{name}" for name in ui_build.CARDS}
FORBIDDEN_IN_CARDS = (
    "http://",
    "https://",
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "<link",
    "@import",
    "src=",
    "innerHTML",
)


class Outline(HTMLParser):
    """Collect tags and attributes to check the document's structure."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.setdefault(tag, dict(attrs))


def run_apps_client(work):
    """Like run_client, but the client advertises MCP Apps support."""

    async def main():
        app = create_app()
        async with app.router.lifespan_context(app):
            http = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url=BASE,
                headers={"X-Greeo-User": "card-listener"},
            )
            extension = advertise(EXTENSION_ID, {"mimeTypes": [APP_MIME_TYPE]})
            transport = streamable_http_client(f"{BASE}/mcp", http_client=http)
            async with http, Client(transport, mode="legacy", extensions=[extension]) as client:
                return await work(client)

    return async_to_sync(main)()


def test_resources_list_returns_all_six_cards_with_the_apps_mime_type() -> None:
    resources = run_client(lambda client: client.list_resources()).resources

    assert {str(resource.uri) for resource in resources} == CARD_URIS
    assert {resource.mime_type for resource in resources} == {APP_MIME_TYPE}
    assert APP_MIME_TYPE == "text/html;profile=mcp-app"


@pytest.mark.parametrize("name", sorted(ui_build.CARDS))
def test_resources_read_returns_small_valid_html(name: str) -> None:
    uri = ui_build.card_uri(name)
    contents = run_client(lambda client: client.read_resource(uri)).contents

    [content] = contents
    assert content.mime_type == APP_MIME_TYPE
    html = content.text
    assert len(html.encode("utf-8")) < ui_build.MAX_CARD_BYTES
    assert html.startswith("<!doctype html>")
    outline = Outline()
    outline.feed(html)
    for tag in ("html", "title", "main", "header", "footer", "h1", "style", "script"):
        assert tag in outline.tags, tag
    assert outline.attributes["html"]["lang"] == "en"
    assert outline.attributes["body"]["data-card"] == name
    assert "__CARD" not in html  # every placeholder was filled


@pytest.mark.parametrize("name", sorted(ui_build.CARDS))
def test_cards_make_no_network_requests_and_use_no_storage(name: str) -> None:
    html = ui_build.read_dist(name)

    assert [needle for needle in FORBIDDEN_IN_CARDS if needle in html] == []
    assert "prefers-reduced-motion" in html
    assert 'aria-label="Parts of this story"' in html
    for method in (
        "ui/initialize",
        "ui/notifications/initialized",
        "ui/notifications/tool-result",
        "ui/notifications/host-context-changed",
        "ui/notifications/size-changed",
        "ui/resource-teardown",
    ):
        assert method in html, method


def test_dist_is_up_to_date() -> None:
    assert ui_build.stale_cards() == [], "Run: python manage.py build_ui"


def test_every_card_tool_links_to_its_resource_and_others_do_not() -> None:
    tools = run_client(lambda client: client.list_tools()).tools

    links = {tool.name: ((tool.meta or {}).get("ui") or {}).get("resourceUri") for tool in tools}
    for name, card in CARD_FOR_TOOL.items():
        assert links[name] == ui_build.card_uri(card)
    assert {name for name, uri in links.items() if uri} == set(CARD_FOR_TOOL)


def test_card_links_are_visible_to_hosts_that_advertise_apps_support() -> None:
    # The spec has the host advertise support; it discovers cards from each tool's _meta.
    tools = run_apps_client(lambda client: client.list_tools()).tools

    linked = {tool.name for tool in tools if ((tool.meta or {}).get("ui") or {}).get("resourceUri")}
    assert linked == set(CARD_FOR_TOOL)


def test_tools_return_full_text_with_and_without_ui_support(story: Story) -> None:
    async def flow(client: Client):
        return [
            await client.call_tool(name, {"story_id": story.pk}) for name in sorted(CARD_FOR_TOOL)
        ]

    plain, with_ui = run_client(flow), run_apps_client(flow)

    for without, with_card in zip(plain, with_ui, strict=True):
        text = " ".join(block.text for block in without.content)
        assert text.strip() and not without.is_error
        assert text == " ".join(block.text for block in with_card.content)
        assert without.structured_content["spoken"] == text


def test_card_data_has_title_progress_and_highlightable_proverbs(story: Story) -> None:
    async def flow(client: Client):
        beat = await client.call_tool("tell_tale", {"story_id": story.pk, "beat": 1})
        moral = await client.call_tool("get_moral", {"story_id": story.pk})
        return beat.structured_content, moral.structured_content

    beat, moral = run_client(flow)

    assert beat["title"] == story.handle
    steps = {step["key"]: step for step in beat["progress"]["steps"]}
    assert list(steps) == [
        "tale",
        "closing",
        "proverbs",
        "facts",
        "context",
        "perspectives",
        "sources",
    ]
    assert steps["tale"]["state"] == "current"
    assert steps["closing"]["label"] == "REFLECTION"
    proverb = beat["proverbs_used"][0]
    assert proverb["spoken_form"] in beat["text"]
    assert [p["slot"] for p in moral["proverbs"]] == ["P1", "P2"]
    assert {step["key"]: step["state"] for step in moral["progress"]["steps"]}["closing"] == (
        "current"
    )


def test_closing_step_is_labelled_moral_only_for_a_moral(story: Story) -> None:
    StoryTelling.objects.filter(story=story).update(closing_kind=StoryTelling.ClosingKind.MORAL)

    result = run_client(lambda client: client.call_tool("get_facts", {"story_id": story.pk}))

    labels = {s["key"]: s["label"] for s in result.structured_content["progress"]["steps"]}
    assert labels["closing"] == "MORAL"


def test_unservable_proverbs_never_reach_the_wisdom_card(story: Story) -> None:
    from apps.wisdom.models import Proverb

    Proverb.objects.filter(pk="pv_synthetic02").update(
        verification_status=Proverb.VerificationStatus.DISPUTED
    )

    result = run_client(lambda client: client.call_tool("get_moral", {"story_id": story.pk}))

    assert [p["slot"] for p in result.structured_content["proverbs"]] == ["P1"]


def test_bridge_uses_only_text_nodes_for_story_content() -> None:
    base = (ui_build.SRC_DIR / "base.html").read_text(encoding="utf-8")

    assert "createTextNode" in base
    assert not re.search(r"\.innerHTML\s*=|insertAdjacentHTML|document\.write", base)
