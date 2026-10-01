"""Identity: demo tokens, the HTTP gate, user isolation, rate limiting and log redaction."""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import Any

import httpx2
import pytest
from apps.core.logging import JsonFormatter, RedactSecrets, redact
from apps.mcp_server import gate
from apps.mcp_server.apps import dev_identity_check
from apps.mcp_server.server import create_app
from apps.memory import services as memory
from apps.memory.models import ApiToken, EndUser, StoryEncounter
from apps.memory.tokens import hash_token, issue_token, revoke_tokens, user_for_token
from apps.stories.models import Story
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from rest_framework.test import APIClient

from tests.test_mcp_server import BASE, GOOD_HEADERS, INITIALIZE

pytestmark = pytest.mark.django_db

# Every tool that reads or changes a listener's memory, with arguments for a story.
MEMORY_TOOLS: dict[str, dict[str, Any]] = {
    "tell_tale": {"beat": 1},
    "get_moral": {},
    "explain_proverb": {},
    "get_facts": {},
    "get_context": {},
    "get_perspectives": {},
    "get_sources": {},
    "save_for_later": {},
    "get_saved_stories": {},
    "set_preferences": {"tone": "light", "regions": ["Elsewhere"]},
}
NEEDS_STORY = set(MEMORY_TOOLS) - {"get_saved_stories", "set_preferences"}


def demo_user(name: str) -> tuple[EndUser, str]:
    user = memory.get_or_create_user(f"demo:{name}")
    return user, issue_token(user, label=name)


def run_as(token: str | None, work, *, extra_headers: dict[str, str] | None = None):
    """Connect the SDK client to the in-process server with a bearer token (or as a guest)."""

    async def main():
        app = create_app()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers.update(extra_headers or {})
        async with app.router.lifespan_context(app):
            http = httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers
            )
            transport = streamable_http_client(f"{BASE}/mcp", http_client=http)
            async with http, Client(transport, mode="legacy") as client:
                return await work(client)

    return async_to_sync(main)()


def post_initialize(headers: dict[str, str]) -> httpx2.Response:
    async def main() -> httpx2.Response:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=BASE
            ) as http:
                return await http.post("/mcp", json=INITIALIZE, headers={**GOOD_HEADERS, **headers})

    return async_to_sync(main)()


# Demo tokens ----------------------------------------------------------------------------


def test_create_demo_user_prints_a_token_once_and_stores_only_its_hash() -> None:
    output = StringIO()

    call_command("create_demo_user", "judge-1", label="demo day", stdout=output)

    printed = output.getvalue()
    token = next(word for word in printed.split() if word.startswith("greeo_"))
    record = ApiToken.objects.get()
    assert record.user.external_id == "demo:judge-1"
    assert record.token_hash == hash_token(token) and len(record.token_hash) == 64
    assert token not in json.dumps(list(ApiToken.objects.values("token_hash", "label")))
    assert "not Alexa+ account linking" in printed
    assert user_for_token(token) == record.user


def test_create_demo_user_can_revoke_older_tokens_and_rejects_odd_names() -> None:
    first = StringIO()
    call_command("create_demo_user", "judge-2", stdout=first)
    old = next(word for word in first.getvalue().split() if word.startswith("greeo_"))

    call_command("create_demo_user", "judge-2", revoke_existing=True, stdout=StringIO())

    assert user_for_token(old) is None
    assert ApiToken.objects.filter(revoked=False).count() == 1
    with pytest.raises(CommandError):
        call_command("create_demo_user", "not a name!", stdout=StringIO())


def test_token_lookup_rejects_unknown_revoked_and_foreign_tokens() -> None:
    user, token = demo_user("ada")

    assert user_for_token(token) == user
    assert user_for_token("greeo_" + "x" * 43) is None
    assert user_for_token("eyJhbGciOi.some.jwt") is None
    revoke_tokens(user)
    assert user_for_token(token) is None


# The HTTP gate ---------------------------------------------------------------------------


def test_a_valid_bearer_token_identifies_the_listener(story: Story) -> None:
    user, token = demo_user("ada")

    run_as(token, lambda client: client.call_tool("tell_tale", {"story_id": story.pk, "beat": 2}))

    assert StoryEncounter.objects.get(user=user, story=story).last_beat == 2
    assert ApiToken.objects.get().last_used_at is not None


def test_unknown_and_revoked_tokens_get_http_401() -> None:
    user, token = demo_user("ada")
    revoke_tokens(user)

    unknown = post_initialize({"Authorization": "Bearer greeo_" + "x" * 43})
    revoked = post_initialize({"Authorization": f"Bearer {token}"})
    guest = post_initialize({})

    assert (unknown.status_code, revoked.status_code) == (401, 401)
    assert unknown.json() == {"error": "unauthorized", "message": "This access token is not valid."}
    assert guest.status_code == 200  # story tools need no identity


def test_a_bearer_token_wins_over_the_dev_header(story: Story, dev_identity) -> None:
    user, token = demo_user("ada")

    run_as(
        token,
        lambda client: client.call_tool("tell_tale", {"story_id": story.pk}),
        extra_headers={"X-Greeo-User": "someone-else"},
    )

    assert list(StoryEncounter.objects.values_list("user__external_id", flat=True)) == ["demo:ada"]


def test_startup_fails_loudly_if_dev_identity_is_on_without_debug() -> None:
    with override_settings(DEBUG=False, MCP_ALLOW_DEV_IDENTITY=True):
        with pytest.raises(ImproperlyConfigured, match="MCP_ALLOW_DEV_IDENTITY is on while DEBUG"):
            create_app()
        [error] = dev_identity_check(None)
        assert error.id == "greeo.E001"
    with override_settings(DEBUG=True, MCP_ALLOW_DEV_IDENTITY=True):
        assert dev_identity_check(None) == []
        create_app()


def test_no_tool_accepts_an_identity_argument() -> None:
    tools = run_as(None, lambda client: client.list_tools()).tools

    forbidden = {"user", "user_id", "external_id", "listener", "token", "account"}
    for tool in tools:
        assert not forbidden & set(tool.input_schema.get("properties", {})), tool.name


# Isolation --------------------------------------------------------------------------------


def snapshot(user: EndUser) -> dict[str, Any]:
    user.refresh_from_db()
    encounters = list(
        StoryEncounter.objects.filter(user=user)
        .order_by("story_id")
        .values("story_id", "tone_heard", "last_beat", "tale_completed", "saved", "layers_explored")
    )
    return {
        "encounters": encounters,
        "preferences": user.preferences,
        "session": memory.get_session_context(user),
    }


def test_every_memory_tool_is_scoped_to_its_own_listener(story: Story) -> None:
    ada, ada_token = demo_user("ada")
    bola, bola_token = demo_user("bola")

    async def ada_listens(client: Client) -> None:
        await client.call_tool("tell_tale", {"story_id": story.pk, "beat": 2})
        await client.call_tool("get_facts", {"story_id": story.pk})
        await client.call_tool("save_for_later", {"story_id": story.pk})
        await client.call_tool("set_preferences", {"tone": "serious", "regions": ["Veloria"]})

    run_as(ada_token, ada_listens)
    before = snapshot(ada)
    assert before["encounters"][0]["saved"] and before["preferences"]["tone"] == "serious"

    # Reading: Bola, with no story named, must never be handed Ada's story or state.
    async def bola_reads(client: Client) -> dict[str, Any]:
        return {
            name: await client.call_tool(name, {})
            for name in MEMORY_TOOLS
            if name != "set_preferences"
        }

    for name, result in run_as(bola_token, bola_reads).items():
        if name == "get_saved_stories":
            assert result.structured_content["stories"] == [], name
        else:
            assert result.structured_content["error"] == "which_story", name
        assert story.handle not in " ".join(block.text for block in result.content), name

    # Mutating: Bola uses every tool on the same story; Ada's state must not move.
    async def bola_acts(client: Client) -> None:
        for name, arguments in MEMORY_TOOLS.items():
            if name in NEEDS_STORY:
                arguments = {**arguments, "story_id": story.pk}
            result = await client.call_tool(name, arguments)
            assert not result.is_error, (name, result.content)
        await client.call_tool("set_preferences", {"reset": True})

    run_as(bola_token, bola_acts)

    assert snapshot(ada) == before
    assert StoryEncounter.objects.get(user=bola, story=story).last_beat == 1
    bola.refresh_from_db()
    assert memory.get_preferences(bola).tone == "light"


def test_guests_never_see_a_listeners_state(story: Story) -> None:
    _, token = demo_user("ada")
    run_as(token, lambda client: client.call_tool("save_for_later", {"story_id": story.pk}))

    async def guest(client: Client):
        return (
            await client.call_tool("get_saved_stories", {}),
            await client.call_tool("tell_tale", {}),
        )

    saved, tale = run_as(None, guest)

    assert saved.structured_content["error"] == "needs_account"
    assert tale.structured_content["error"] == "which_story"


# Rate limiting ----------------------------------------------------------------------------


class MinuteCounter:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> bool:
        return True


def test_requests_are_limited_per_token(monkeypatch) -> None:
    counter = MinuteCounter()
    monkeypatch.setattr(gate, "rate_counter", lambda: counter)
    _, ada = demo_user("ada")
    _, bola = demo_user("bola")

    with override_settings(MCP_RATE_LIMIT_PER_MINUTE=3):
        statuses = [
            post_initialize({"Authorization": f"Bearer {ada}"}).status_code for _ in range(5)
        ]
        limited = post_initialize({"Authorization": f"Bearer {ada}"})
        other = post_initialize({"Authorization": f"Bearer {bola}"})

    assert statuses == [200, 200, 200, 429, 429]
    assert limited.headers["retry-after"] == "60"
    assert other.status_code == 200
    assert not any(ada in key or bola in key for key in counter.counts)  # buckets hold no tokens


def test_rate_limit_is_off_at_zero_and_survives_a_redis_outage(monkeypatch) -> None:
    import redis

    class Broken:
        def incr(self, key: str) -> int:
            raise redis.ConnectionError("synthetic outage")

    with override_settings(MCP_RATE_LIMIT_PER_MINUTE=0):
        assert gate.over_limit("t:any", MinuteCounter()) is False
    with override_settings(MCP_RATE_LIMIT_PER_MINUTE=1):
        assert gate.over_limit("t:any", Broken()) is False


# Logs -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer greeo_abcdefghijklmnopqrstuvwxyz012345",
        "headers={'authorization': 'Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig'}",
        "token=greeo_abcdefghijklmnopqrstuvwxyz012345&next=1",
        '{"access_token": "abc123secretvalue", "refresh_token": "def456secretvalue"}',
        "client_secret=supersecretvalue",
        "stray greeo_abcdefghijklmnopqrstuvwxyz012345 in a sentence",
    ],
)
def test_redaction_removes_credentials(line: str) -> None:
    cleaned = redact(line)

    for secret in ("greeo_abc", "eyJhbGci", "abc123secret", "def456secret", "supersecret"):
        assert secret not in cleaned
    assert "[redacted]" in cleaned


def test_log_records_are_redacted_and_formatted_as_json() -> None:
    secret = "Authorization: Bearer greeo_" + "a" * 40
    arguments = ("listener 7", secret)
    message = "call failed for %s with %s"
    record = logging.LogRecord("greeo.test", logging.WARNING, __file__, 1, message, arguments, None)

    assert RedactSecrets().filter(record) is True
    entry = json.loads(JsonFormatter().format(record))

    assert entry["level"] == "WARNING" and entry["logger"] == "greeo.test"
    assert "greeo_aaaa" not in entry["message"] and "[redacted]" in entry["message"]
    assert "listener 7" in entry["message"]


def test_exceptions_in_logs_are_redacted_too() -> None:
    try:
        raise ValueError("bad token greeo_" + "b" * 40)
    except ValueError:
        import sys

        record = logging.LogRecord(
            "greeo.test", logging.ERROR, __file__, 1, "boom", None, sys.exc_info()
        )

    RedactSecrets().filter(record)
    entry = json.loads(JsonFormatter().format(record))

    assert "greeo_bbbb" not in json.dumps(entry) and "ValueError" in entry["error"]


def test_the_console_handler_redacts_and_uses_json() -> None:
    console = settings.LOGGING["handlers"]["console"]

    assert console["filters"] == ["redact"] and console["formatter"] == "json"
    assert settings.LOGGING["filters"]["redact"]["()"] == "apps.core.logging.RedactSecrets"


def test_tool_calls_never_log_the_token_or_the_listeners_name(story: Story, caplog) -> None:
    _, token = demo_user("ada-lovelace")

    async def flow(client: Client) -> None:
        await client.call_tool("tell_tale", {"story_id": story.pk})
        await client.call_tool("tell_tale", {"story_id": "st_missing"})
        await client.call_tool("get_facts", {"story_id": "not an id"})

    with caplog.at_level(logging.DEBUG):
        run_as(token, flow)
        post_initialize({"Authorization": "Bearer greeo_" + "z" * 43})

    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in logged and "greeo_zzzz" not in logged
    assert "ada-lovelace" not in logged


# The simulator -----------------------------------------------------------------------------


def test_simulator_forwards_a_bearer_token_to_mcp(story: Story, monkeypatch) -> None:
    from apps.simulator import host as host_module
    from apps.simulator.state import SessionStore

    from tests.test_simulator import FakeRedis, in_process

    store = SessionStore(client=FakeRedis())
    monkeypatch.setattr(host_module, "connect", in_process)
    monkeypatch.setattr(host_module, "SessionStore", lambda: store)
    user, token = demo_user("ada")
    api = APIClient(headers={"Authorization": f"Bearer {token}"})

    response = api.post(
        "/api/simulator/turn",
        {"session_id": "token-1", "text": "tell me about the footbridge"},
        format="json",
    )

    assert response.json()["display"]["structured"]["beat"] == 1
    assert StoryEncounter.objects.get(user=user, story=story).last_beat == 1


def test_simulator_explains_a_rejected_token(story: Story, monkeypatch) -> None:
    from apps.simulator import host as host_module
    from apps.simulator.state import SessionStore

    from tests.test_simulator import FakeRedis, in_process

    store = SessionStore(client=FakeRedis())
    monkeypatch.setattr(host_module, "connect", in_process)
    monkeypatch.setattr(host_module, "SessionStore", lambda: store)
    user, token = demo_user("ada")
    revoke_tokens(user)
    api = APIClient(headers={"Authorization": f"Bearer {token}"})

    async def in_process_status(credentials: dict[str, str]) -> int:
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=credentials
            ) as http:
                return (await http.post("/mcp", json=INITIALIZE, headers=GOOD_HEADERS)).status_code

    monkeypatch.setattr(host_module, "http_status", in_process_status)

    body = {"session_id": "token-2", "text": "what was I listening to?"}
    response = api.post("/api/simulator/turn", body, format="json")

    assert response.json()["spoken"] == host_module.SIGN_IN_AGAIN
    assert response.json()["tool_trace"] == []
