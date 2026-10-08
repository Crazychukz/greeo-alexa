"""End-to-end smoke test of a running Greeo MCP server, using the official SDK client.

Runs the core path from the Phase 9 acceptance: search -> beats 1..N -> moral ->
explain_proverb -> facts -> context -> perspectives -> sources -> save -> a fresh
session -> get_saved_stories, printing each spoken reply and exiting non-zero on the first
unexpected result.

Usage (after `make up && make migrate && make seed`):
    python scripts/mcp_smoke.py [http://127.0.0.1:8001/mcp] [--user some-listener]

Each run uses a new listener by default, so remembered history never hides the flow.
"""

from __future__ import annotations

import argparse
import sys
from uuid import uuid4

import anyio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {
    "search_events",
    "get_briefing",
    "get_demo_stories",
    "get_help",
    "tell_tale",
    "get_moral",
    "explain_proverb",
    "get_facts",
    "get_context",
    "get_perspectives",
    "get_sources",
    "save_for_later",
    "get_saved_stories",
    "set_preferences",
}


def show(name: str, result) -> dict:
    text = " ".join(getattr(block, "text", "") for block in result.content)
    marker = "ERROR" if result.is_error else "ok"
    print(f"\n[{marker}] {name}\n  spoken: {text}")
    data = result.structured_content or {}
    if data.get("next_options"):
        print(f"  next:   {', '.join(data['next_options'])}")
    return data


def expect(condition: bool, message: str) -> None:
    if not condition:
        print(f"\nSMOKE FAILED: {message}")
        sys.exit(1)


async def main(url: str, user: str) -> None:
    async with httpx2.AsyncClient(headers={"X-Greeo-User": user}) as http:
        async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            print(f"tools/list: {', '.join(sorted(tools))}")
            expect(tools == EXPECTED_TOOLS, f"unexpected tool list {sorted(tools)}")

            briefing = show("get_briefing", await client.call_tool("get_briefing", {}))
            expect(bool(briefing.get("stories")), "briefing returned no stories; run make seed")

            # Search for a word from the first listed story: works on seeded or real news.
            first = briefing["stories"][0]
            query = max(first["title"].split(), key=len).strip(".,:;'\"")
            found = show("search_events", await client.call_tool("search_events", {"query": query}))
            expect(bool(found.get("stories")), f"search for {query!r} found nothing")
            story_id = first["story_id"]

            helped = show("get_help", await client.call_tool("get_help", {}))
            expect(bool(helped.get("abilities")), "get_help listed nothing")
            show("get_demo_stories", await client.call_tool("get_demo_stories", {}))

            beat, has_more = 1, True
            while has_more:
                data = show(
                    f"tell_tale beat {beat}",
                    await client.call_tool("tell_tale", {"story_id": story_id, "beat": beat}),
                )
                expect("beats_total" in data, "tell_tale did not return a beat")
                has_more, beat = data["has_more"], beat + 1

            for tool in (
                "get_moral",
                "explain_proverb",
                "get_facts",
                "get_context",
                "get_perspectives",
                "get_sources",
            ):
                result = await client.call_tool(tool, {"story_id": story_id})
                show(tool, result)
                expect(not result.is_error, f"{tool} returned an error")

            saved = show("save_for_later", await client.call_tool("save_for_later", {}))
            expect(saved.get("saved") is True, "save_for_later did not save the story")

            unknown = await client.call_tool("tell_tale", {"story_id": "st_missing"})
            show("tell_tale (unknown story, expected friendly error)", unknown)
            expect(unknown.is_error, "unknown story should be a friendly error")

        print("\n--- fresh session ---")
        async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
            listing = show("get_saved_stories", await client.call_tool("get_saved_stories", {}))
            titles = [item["story_id"] for item in listing.get("stories", [])]
            expect(story_id in titles, "the saved story is missing in a fresh session")

    print("\nSMOKE PASSED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8001/mcp")
    parser.add_argument("--user", default=f"smoke-{uuid4().hex[:8]}")
    arguments = parser.parse_args()
    anyio.run(main, arguments.url, arguments.user)
