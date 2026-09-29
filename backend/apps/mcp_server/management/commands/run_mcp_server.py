"""Run Greeo's MCP server (Streamable HTTP) as its own process."""

from __future__ import annotations

from typing import Any

import uvicorn
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.mcp_server.server import create_app


class Command(BaseCommand):
    help = "Serve the MCP endpoint at /mcp and a health check at /healthz."

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write(f"Greeo MCP server on http://{settings.MCP_HOST}:{settings.MCP_PORT}/mcp")
        uvicorn.run(create_app(), host=settings.MCP_HOST, port=settings.MCP_PORT, log_level="info")
