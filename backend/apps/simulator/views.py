"""HTTP API for the simulated Alexa+ front end. Thin: the work is in host.py and speech.py."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.mcp_server.identity import dev_identity_enabled
from apps.stories.models import Story

from . import host, speech
from .mcp_link import CARD_PREFIX, DEV_USER_HEADER

logger = logging.getLogger(__name__)
SESSION_ID = serializers.RegexField(r"^[A-Za-z0-9_-]{1,64}$")
DEMO_LIMIT = 12


class TurnInput(serializers.Serializer):
    session_id = SESSION_ID
    text = serializers.CharField(max_length=500, trim_whitespace=True)
    # Set when the listener tapped a story on screen: tell that story.
    story_id = serializers.RegexField(r"^st_[a-z0-9]{1,12}$", required=False)
    # Set when Greeo carries on with its own tale: the next part, or the closing thought.
    follow_up = serializers.ChoiceField(["next_beat", "closing"], required=False)

    def validate(self, attrs: dict) -> dict:
        if attrs.get("follow_up") and not attrs.get("story_id"):
            raise serializers.ValidationError({"story_id": "A follow-up needs the story."})
        return attrs


class ResetInput(serializers.Serializer):
    session_id = SESSION_ID


class SpeechInput(serializers.Serializer):
    text = serializers.CharField(max_length=speech.MAX_CHUNK_CHARS, trim_whitespace=True)
    voice = serializers.CharField(max_length=24, required=False, allow_blank=True)


def credentials(request: Request) -> dict[str, str]:
    """The caller's identity headers, passed on to MCP unchanged. Empty means a guest.

    A demo bearer token is always forwarded (MCP validates it). The development header
    is forwarded only when dev identity is enabled, and MCP checks that again.
    """
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        return {"Authorization": authorization}
    dev_user = (request.headers.get(DEV_USER_HEADER) or "").strip()[:200]
    if dev_identity_enabled() and dev_user:
        return {DEV_USER_HEADER: dev_user}
    return {}


@api_view(["POST"])
def turn(request: Request) -> Response:
    data = TurnInput(data=request.data)
    data.is_valid(raise_exception=True)
    result = host.run_turn(
        data.validated_data["session_id"],
        data.validated_data["text"],
        credentials(request),
        story_id=data.validated_data.get("story_id"),
        follow_up=data.validated_data.get("follow_up"),
    )
    return Response(result.as_dict())


@api_view(["GET"])
def stories(request: Request) -> Response:
    """The home screen's Demo stories card: demo stories, and how many news stories wait."""
    published = Story.objects.listable().filter(status=Story.Status.PUBLISHED)
    demo = published.filter(is_demo=True).order_by("-published_at")[:DEMO_LIMIT]
    return Response(
        {
            "demo": [
                {
                    "story_id": story.pk,
                    "title": story.handle,
                    "region": story.region,
                    "tones": sorted(story.tellings.values_list("tone", flat=True)),
                }
                for story in demo.prefetch_related("tellings")
            ],
            "news_count": published.filter(
                is_demo=False, published_at__gte=timezone.now() - timedelta(hours=48)
            ).count(),
        }
    )


@api_view(["POST"])
def reset(request: Request) -> Response:
    data = ResetInput(data=request.data)
    data.is_valid(raise_exception=True)
    host.reset_session(data.validated_data["session_id"], credentials(request))
    return Response({"reset": True})


@api_view(["GET"])
def resource(request: Request) -> Response:
    """Proxy resources/read, for Greeo's own cards only."""
    uri = request.query_params.get("uri", "")
    if not uri.startswith(CARD_PREFIX):
        return Response({"detail": "Only ui://greeo/ resources are available."}, status=400)
    try:
        mime_type, text = host.read_card(uri, credentials(request))
    except Exception:
        logger.warning("Could not read card %s", uri, exc_info=True)
        return Response({"detail": "That card is not available."}, status=404)
    return Response({"uri": uri, "mime_type": mime_type, "text": text})


@api_view(["POST"])
def tts(request: Request) -> HttpResponse:
    """Audio for one sentence, or 204 so the front end uses browser speech."""
    data = SpeechInput(data=request.data)
    data.is_valid(raise_exception=True)
    audio = speech.synthesize_sentence(
        data.validated_data["text"], data.validated_data.get("voice") or None
    )
    if audio is None:
        return HttpResponse(status=204)
    response = HttpResponse(audio.audio, content_type=audio.content_type)
    response["X-Greeo-Speech-Cache"] = "hit" if audio.cached else "miss"
    return response
