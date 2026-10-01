"""The simulator's only route to Greeo: an MCP client over Streamable HTTP.

Like Alexa+, the host discovers tools with tools/list and calls them with tools/call. It
never reads Greeo's database and never hard-codes a reply.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx2
from django.conf import settings
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

CARD_PREFIX = "ui://greeo/"
DEV_USER_HEADER = "X-Greeo-User"


@dataclass(frozen=True)
class ToolOutcome:
    """One tool call, as the trace shows it and as the reply uses it."""

    tool: str
    args: dict[str, Any]
    ms: int
    ok: bool
    spoken: str
    structured: dict[str, Any] = field(default_factory=dict)
    resource_uri: str | None = None

    def trace(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "ms": self.ms, "ok": self.ok}


class McpLink:
    """A connected MCP client plus the tool metadata fetched for this turn."""

    def __init__(self, client: Client) -> None:
        self.client = client
        self._tools: list[dict[str, Any]] | None = None

    async def tools(self) -> list[dict[str, Any]]:
        """tools/list, once per turn: name, description, input schema and linked card."""
        if self._tools is None:
            listed = (await self.client.list_tools()).tools
            self._tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.input_schema,
                    "resource_uri": ((tool.meta or {}).get("ui") or {}).get("resourceUri"),
                }
                for tool in listed
            ]
        return self._tools

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        """tools/call, timed. Error results are returned, not raised: they are speakable."""
        arguments = {key: value for key, value in arguments.items() if value is not None}
        cards = {tool["name"]: tool["resource_uri"] for tool in await self.tools()}
        started = time.monotonic()
        result = await self.client.call_tool(name, arguments)
        elapsed = round((time.monotonic() - started) * 1000)
        spoken = " ".join(getattr(block, "text", "") for block in result.content).strip()
        return ToolOutcome(
            tool=name,
            args=arguments,
            ms=elapsed,
            ok=not result.is_error,
            spoken=spoken,
            structured=dict(result.structured_content or {}),
            resource_uri=cards.get(name) if not result.is_error else None,
        )

    async def read_card(self, uri: str) -> tuple[str, str]:
        """resources/read for one of Greeo's cards; returns (mime type, html)."""
        if not uri.startswith(CARD_PREFIX):
            raise ValueError("Only Greeo card resources can be read.")
        [content] = (await self.client.read_resource(uri)).contents
        return content.mime_type, content.text


# The identity headers to forward to MCP: a bearer token, the dev header, or nothing.
Credentials = dict[str, str]
Connector = Callable[[Credentials], AbstractAsyncContextManager[McpLink]]


@asynccontextmanager
async def connect(credentials: Credentials) -> AsyncIterator[McpLink]:
    """Connect to the MCP server as this listener, or as a guest with no credentials.

    The simulator never decides who the listener is: it passes the caller's credentials
    on, and the MCP server resolves the identity, as it would for Alexa+.
    """
    async with httpx2.AsyncClient(headers=credentials, timeout=15) as http:
        transport = streamable_http_client(settings.SIMULATOR_MCP_URL, http_client=http)
        async with Client(transport, mode="legacy") as client:
            yield McpLink(client)


PROBE = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "greeo-simulator-probe", "version": "1"},
    },
}


async def http_status(credentials: Credentials) -> int | None:
    """How MCP answers these credentials over plain HTTP, or None if it cannot be reached.

    The SDK client reports every HTTP error as the same generic failure, so after a
    failed turn the host asks once more to tell "token rejected" (401) and "slow down"
    (429) apart from "server down".
    """
    try:
        async with httpx2.AsyncClient(headers=credentials, timeout=5) as http:
            response = await http.post(
                settings.SIMULATOR_MCP_URL,
                json=PROBE,
                headers={"Accept": "application/json, text/event-stream"},
            )
        return response.status_code
    except httpx2.HTTPError:
        return None
