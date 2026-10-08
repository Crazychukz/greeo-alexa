"""Greeo's MCP server: tool registration, error hygiene, health route and HTTP app.

Why a separate process: the official SDK manages its own async lifecycle (Starlette,
anyio task groups, a session manager started in the app lifespan). Mounting that inside
Django's ASGI handler would couple two lifecycles; running it as its own process via
`manage.py run_mcp_server` keeps both simple while sharing models, services and the DB.

Why sync_to_async: Django's ORM is synchronous and refuses to run on an event loop. The
async tool functions below read the request headers, then run the handler in a thread
with `thread_sensitive=True`, which keeps all ORM work on one thread, the pattern
Django documents for calling the ORM from async code.

This module deliberately does not use `from __future__ import annotations`: the SDK
builds each tool's JSON Schema from its real, evaluated annotations.
"""

import logging
from collections.abc import Callable
from typing import Annotated, Any, Literal

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections, connection
from mcp.server.apps import Apps
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from apps.core.services import get_health_report

from . import handlers, schemas, ui_build
from .gate import IdentityGate
from .identity import assert_safe_identity_settings, current_user
from .voice import BeatTooLongError, VoiceSafetyError, finalize, friendly_error

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Greeo retells verified news as short spoken tales inspired by African oral storytelling "
    "traditions, woven with verified proverbs, then lets the listener ask for the truth behind "
    "each tale: the closing thought, the proverb explained, facts, context, perspectives and "
    "sources. Every result has a `spoken` field written to be read aloud as written: please "
    "relay tale beats faithfully and in full, because the wording and proverbs are checked "
    "against the facts. Tell a tale one beat at a time. The listener may jump to any layer at "
    "any time and later continue the tale; never require the layers in order. When asked "
    "what Greeo can do: it finds today's stories or stories on a topic, tells them as tales "
    "in a light, balanced or serious tone, explains the proverbs, gives the facts, "
    "background, perspectives and sources, remembers saved stories and where the "
    "listener stopped, and tells behind-the-scenes tales about how it was built. For that "
    "question, call get_help: its answer fits where the listener is."
)

StoryId = Annotated[
    Annotated[str, Field(min_length=3, max_length=32, pattern=r"^st_[a-z0-9]+$")] | None,
    Field(
        description=(
            "The story_id returned by search_events, get_briefing or get_saved_stories. "
            "Leave empty to use the story the listener is currently hearing."
        )
    ),
]
Page = Annotated[int, Field(ge=1, le=20, description="Page of results, starting at 1.")]
Region = Annotated[
    str | None,
    Field(
        max_length=100,
        description="Optional country or region, for example Nigeria, Kenya, East Africa.",
    ),
]
Tone = Annotated[
    Literal["light", "balanced", "serious"] | None,
    Field(
        description=(
            "Optional telling style: light (playful), balanced (default), or serious "
            "(sober). Also called mood or style. Leave empty to use the listener's preference."
        )
    ),
]

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
# Layer tools only record listening progress, which is idempotent and never destructive.
REMEMBERS = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
SPOKEN_NOTE = " The `spoken` field is plain text written to be read aloud as written."


# Running handlers safely ---------------------------------------------------------------


async def run_handler(
    handler: Callable[..., schemas.Envelope], ctx: Context, **arguments: Any
) -> CallToolResult:
    """Resolve the caller from the request, then run the handler off the event loop."""
    headers = dict(ctx.headers or {})
    return await sync_to_async(_invoke, thread_sensitive=True)(handler, headers, arguments)


def _invoke(
    handler: Callable[..., schemas.Envelope], headers: dict[str, str], arguments: dict[str, Any]
) -> CallToolResult:
    _release_stale_connection()
    try:
        user = current_user(headers)
        result = handler(user, **arguments)
        result = finalize(result, verbatim=handler is handlers.tell_tale)
    except handlers.FriendlyError as error:
        return friendly_result(error.kind, error.spoken, error.next_options)
    except (VoiceSafetyError, BeatTooLongError):
        # A data or code error: the reply broke a voice rule. Log it; never speak it.
        logger.exception("Tool %s produced a reply that failed the voice gate", handler.__name__)
        return friendly_result("unexpected", *friendly_error("unexpected"))
    except Exception:
        logger.exception("Tool handler %s failed", getattr(handler, "__name__", handler))
        return friendly_result("unexpected", *friendly_error("unexpected"))
    finally:
        _release_stale_connection()
    return CallToolResult(
        content=[TextContent(type="text", text=result.spoken)],
        structured_content=result.model_dump(mode="json"),
    )


def _release_stale_connection() -> None:
    """Drop expired DB connections between calls, as Django does between requests."""
    if not connection.in_atomic_block:
        close_old_connections()


def friendly_result(kind: str, spoken: str, next_options: list[str]) -> CallToolResult:
    """An `isError` result whose text is safe to speak and says what to do next.

    Errors pass the same voice gate; one that echoes a listener's words containing a
    forbidden term falls back to a generic message.
    """
    try:
        gated = finalize(schemas.Envelope(spoken=spoken, next_options=next_options))
    except VoiceSafetyError:
        gated = schemas.Envelope(spoken=friendly_error("invalid_request")[0], next_options=[])
    spoken, next_options = gated.spoken, gated.next_options
    return CallToolResult(
        content=[TextContent(type="text", text=spoken)],
        structured_content={"error": kind, "spoken": spoken, "next_options": next_options},
        is_error=True,
    )


async def friendly_errors(ctx: Any, call_next: Callable[[Any], Any]) -> Any:
    """Rewrite any error the SDK produced itself (bad arguments, unknown tool) into plain words.

    The SDK puts the exception text in the result, for example "Error executing tool
    tell_tale: 1 validation error ... https://errors.pydantic.dev/...". Alexa+ requires
    that no tool names, field names or jargon reach the customer. At this layer the SDK
    hands over the wire-format dict (camelCase keys), so both forms are handled.
    """
    result = await call_next(ctx)
    if ctx.method != "tools/call" or not _is_unhandled_error(result):
        return result
    logger.info("Rewrote tool error for the listener: %r", _error_text(result)[:500])
    friendly = friendly_result("invalid_request", *friendly_error("invalid_request"))
    if isinstance(result, dict):
        return friendly.model_dump(mode="json", by_alias=True, exclude_none=True)
    return friendly


def _is_unhandled_error(result: Any) -> bool:
    """An error result that did not come from friendly_result (ours carry an error kind)."""
    if isinstance(result, CallToolResult):
        return bool(result.is_error) and not (result.structured_content or {}).get("error")
    if isinstance(result, dict):
        return bool(result.get("isError")) and not (result.get("structuredContent") or {}).get(
            "error"
        )
    return False


def _error_text(result: Any) -> str:
    content = result.get("content", []) if isinstance(result, dict) else result.content
    texts = [
        block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
        for block in content
    ]
    return " ".join(texts)


# Tools --------------------------------------------------------------------------------


async def search_events(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            min_length=1,
            max_length=200,
            description="What the listener wants a story about: a topic, place, person or theme.",
        ),
    ],
    region: Region = None,
    page: Page = 1,
) -> Annotated[CallToolResult, schemas.StoryList]:
    return await run_handler(handlers.search_events, ctx, query=query, region=region, page=page)


async def get_briefing(
    ctx: Context, region: Region = None, page: Page = 1
) -> Annotated[CallToolResult, schemas.StoryList]:
    return await run_handler(handlers.get_briefing, ctx, region=region, page=page)


async def tell_tale(
    ctx: Context,
    story_id: StoryId = None,
    beat: Annotated[
        int | None,
        Field(
            ge=1,
            le=20,
            description=(
                "Which part of the tale to tell, starting at 1. Leave empty to continue "
                "where the listener stopped."
            ),
        ),
    ] = None,
    tone: Tone = None,
) -> Annotated[CallToolResult, schemas.TaleBeat]:
    return await run_handler(handlers.tell_tale, ctx, story_id=story_id, beat=beat, tone=tone)


async def get_demo_stories(
    ctx: Context, page: Page = 1
) -> Annotated[CallToolResult, schemas.StoryList]:
    return await run_handler(handlers.get_demo_stories, ctx, page=page)


async def get_help(ctx: Context) -> Annotated[CallToolResult, schemas.HelpResult]:
    return await run_handler(handlers.get_help, ctx)


async def get_moral(
    ctx: Context, story_id: StoryId = None
) -> Annotated[CallToolResult, schemas.ClosingThought]:
    return await run_handler(handlers.get_moral, ctx, story_id=story_id)


async def explain_proverb(
    ctx: Context,
    story_id: StoryId = None,
    which: Annotated[
        int, Field(ge=1, le=5, description="Which proverb in the tale, starting at 1.")
    ] = 1,
) -> Annotated[CallToolResult, schemas.ProverbExplanation]:
    return await run_handler(handlers.explain_proverb, ctx, story_id=story_id, which=which)


async def get_facts(
    ctx: Context, story_id: StoryId = None
) -> Annotated[CallToolResult, schemas.FactList]:
    return await run_handler(handlers.get_facts, ctx, story_id=story_id)


async def get_context(
    ctx: Context, story_id: StoryId = None
) -> Annotated[CallToolResult, schemas.ContextList]:
    return await run_handler(handlers.get_context, ctx, story_id=story_id)


async def get_perspectives(
    ctx: Context, story_id: StoryId = None
) -> Annotated[CallToolResult, schemas.PerspectiveList]:
    return await run_handler(handlers.get_perspectives, ctx, story_id=story_id)


async def get_sources(
    ctx: Context, story_id: StoryId = None
) -> Annotated[CallToolResult, schemas.SourceList]:
    return await run_handler(handlers.get_sources, ctx, story_id=story_id)


async def save_for_later(
    ctx: Context, story_id: StoryId = None
) -> Annotated[CallToolResult, schemas.SaveResult]:
    return await run_handler(handlers.save_for_later, ctx, story_id=story_id)


async def get_saved_stories(ctx: Context) -> Annotated[CallToolResult, schemas.SavedList]:
    return await run_handler(handlers.get_saved_stories, ctx)


async def set_preferences(
    ctx: Context,
    tone: Tone = None,
    regions: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=100)]] | None,
        Field(
            max_length=5,
            description=(
                "Regions or countries to focus on, for example Nigeria or East Africa. An "
                "empty list means stories from everywhere. Leave out to keep the current choice."
            ),
        ),
    ] = None,
    topics: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=80)]] | None,
        Field(
            max_length=5,
            description=(
                "Themes to prefer, such as community, health, leadership, trade or courage. "
                "Leave out to keep the current choice."
            ),
        ),
    ] = None,
    reset: Annotated[
        bool,
        Field(
            description=(
                "True when the listener says start over or start fresh: clears the current "
                "conversation. Saved stories and history are kept."
            )
        ),
    ] = False,
) -> Annotated[CallToolResult, schemas.PreferencesResult]:
    return await run_handler(
        handlers.set_preferences, ctx, tone=tone, regions=regions, topics=topics, reset=reset
    )


TOOLS: list[tuple[Callable[..., Any], str, str, ToolAnnotations]] = [
    (
        search_events,
        "Find stories",
        "Call when the listener names a topic, place, person or theme (for example 'tell me "
        "about the footbridge' or 'any news from Kenya'). Returns up to five stories with their "
        "story_id. Do not use when no topic is given; use get_briefing instead.",
        READ_ONLY,
    ),
    (
        get_briefing,
        "Today's stories",
        "Call when the listener asks what's new, for today's stories or a briefing, without "
        "naming a topic. Returns up to five recent stories with their story_id, in the "
        "listener's preferred region when they have one. Do not use to search a topic.",
        READ_ONLY,
    ),
    (
        get_demo_stories,
        "Behind the scenes",
        "Call when the listener asks for the demo stories, behind-the-scenes stories, or how "
        "Greeo was built. Returns up to five tales about building Greeo, each with a story_id "
        "for tell_tale. They are not news and never appear among today's stories.",
        READ_ONLY,
    ),
    (
        get_help,
        "What Greeo can do",
        "Call when the listener asks what Greeo can do, for help, or how to use it. Returns a "
        "short summary that starts from where they are (for example a tale they can "
        "continue) and suggestions to try. Do not use to find or tell a story.",
        READ_ONLY,
    ),
    (
        tell_tale,
        "Tell the tale",
        "Call to tell a story as a spoken tale, ONE beat per call. When the listener says "
        "continue, go on or what happened next, call it with no beat (it resumes where they "
        "stopped) or with beat+1. With no story_id it uses the story they are hearing. Returns "
        "the beat text (proverbs already woven in), beats_total, has_more and next_options. "
        "Relay the beat in full. Do not use for facts, sources or the moral; those have "
        "their own tools.",
        REMEMBERS,
    ),
    (
        get_moral,
        "The closing thought",
        "Call when the listener asks for the moral, the lesson, the point or the reflection "
        "of a tale. Returns closing_kind (moral, reflection or none) and its text. Sensitive or "
        "contested stories may have only a neutral reflection or no closing lesson at all.",
        REMEMBERS,
    ),
    (
        explain_proverb,
        "Explain the proverb",
        "Call when the listener asks what a proverb in the tale means, where it comes from or "
        "what it was in the original language. Returns the proverb's culture, language, "
        "meaning, original wording and source. Do not use to tell the tale.",
        REMEMBERS,
    ),
    (
        get_facts,
        "What actually happened",
        "Call when the listener asks what really happened, whether the tale is true, or for the "
        "facts or details. Returns the checked facts with publisher names and dates. Can be "
        "called at any point, even mid-tale; the tale can be continued afterwards.",
        REMEMBERS,
    ),
    (
        get_context,
        "The background",
        "Call when the listener asks for background, why this matters or what it could lead "
        "to. Returns sourced background, why-it-matters and consequence notes.",
        REMEMBERS,
    ),
    (
        get_perspectives,
        "Different perspectives",
        "Call when the listener asks what different sides, people or groups think, or for "
        "other views. Returns materially different sourced viewpoints, or a plain message when "
        "the sources do not support distinct views.",
        REMEMBERS,
    ),
    (
        get_sources,
        "The sources",
        "Call when the listener asks where this came from, who reported it or for the sources. "
        "Returns one card per source with publisher, headline and date, and which layers it "
        "supports. Links are not included by default; never read links aloud.",
        REMEMBERS,
    ),
    (
        save_for_later,
        "Save for later",
        "Call when the listener says save this, remember this story or keep it for later. "
        "With no story_id it saves the story they are hearing. Needs a linked account.",
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    ),
    (
        get_saved_stories,
        "My saved stories",
        "Call when the listener asks for their saved stories, what they were listening to, or "
        "to pick up where they left off. Returns saved stories and the latest unfinished tale, "
        "each with a resume hint such as continue at beat 3. Needs a linked account.",
        READ_ONLY,
    ),
    (
        set_preferences,
        "Preferences",
        "Call when the listener changes how stories are told or chosen: a tone (make it "
        "serious, lighter please), regions (only Nigeria, stories from everywhere) or topics. "
        "Only the values given change; others are kept. Set reset when they say start over. "
        "Needs a linked account.",
        ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    ),
]


# Which card renders each tool's result (MCP Apps). Tools not listed are voice-only.
CARD_FOR_TOOL = {
    "tell_tale": "tale",
    "get_moral": "wisdom",
    "explain_proverb": "wisdom",
    "get_facts": "facts",
    "get_context": "context",
    "get_perspectives": "perspectives",
    "get_sources": "sources",
}


def build_apps() -> Apps:
    """Register the six cards as `ui://` resources served as `text/html;profile=mcp-app`.

    Each card is one self-contained file with no network access, so no CSP domains are
    declared and the host's restrictive default policy applies.
    """
    apps = Apps()
    for name, (title, description) in ui_build.CARDS.items():
        apps.add_html_resource(
            ui_build.card_uri(name),
            ui_build.read_dist(name),
            name=f"greeo-{name}",
            title=title,
            description=description,
            prefers_border=False,
        )
    return apps


def build_server() -> MCPServer:
    server = MCPServer(
        name="greeo",
        title="Greeo",
        description="News retold as voice-first tales with verified proverbs and checkable facts.",
        instructions=INSTRUCTIONS,
        version="0.10.0",
        middleware=[friendly_errors],
        extensions=[build_apps()],
    )
    for fn, title, description, annotations in TOOLS:
        card = CARD_FOR_TOOL.get(fn.__name__)
        server.add_tool(
            fn,
            name=fn.__name__,
            title=title,
            description=description + SPOKEN_NOTE,
            annotations=annotations,
            # The spec's link from a tool to its UI resource. Results are identical with or
            # without a card, so hosts without MCP Apps keep the full spoken text.
            meta={"ui": {"resourceUri": ui_build.card_uri(card)}} if card else None,
            structured_output=True,
        )

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(request: Request) -> JSONResponse:
        report = await sync_to_async(get_health_report, thread_sensitive=True)()
        return JSONResponse(report, status_code=200 if report["status"] == "ok" else 503)

    return server


def transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection is always on: the SDK only enables it for localhost binds."""
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=list(settings.MCP_ALLOWED_HOSTS),
        allowed_origins=list(settings.MCP_ALLOWED_ORIGINS),
    )


def create_app() -> Starlette:
    """Stateless Streamable HTTP with JSON responses: every call stands alone."""
    assert_safe_identity_settings()
    app = build_server().streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(),
        host=settings.MCP_HOST,
    )
    # Reject unknown bearer tokens (401) and excessive request rates (429) before MCP.
    app.add_middleware(IdentityGate, path="/mcp")
    return app


def output_model(tool_name: str) -> type[BaseModel]:
    """The structured model a tool returns, for tests and the smoke script."""
    for fn, *_ in TOOLS:
        if fn.__name__ == tool_name:
            return fn.__annotations__["return"].__metadata__[0]
    raise KeyError(tool_name)
