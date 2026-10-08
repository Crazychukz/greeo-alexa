"""Speech for the simulator: one sentence at a time, paced by the storyteller voice.

Real Alexa+ devices speak for themselves; this exists only so our simulated host can be
heard. The front end splits a beat into sentences and plays them in order, an idea kept
from the first Greeo prototype. Pacing markup (SSML) changes rate and pauses only: it
never adds a word, because Greeo speaks exactly the text that was checked.
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol
from xml.sax.saxutils import escape

import redis
from django.conf import settings

from apps.stories.voices import VOICE_STYLES, VoiceStyle

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 600
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
CLAUSE_PAUSE = re.compile(r"\s*([,;:])\s+")
PAUSE_MARK = "␞"  # a symbol that never occurs in story text
RETRYABLE = {"ThrottlingException", "ServiceFailureException"}


class SpeechUnavailable(Exception):
    """Audio could not be produced; the caller falls back to the browser's own voice."""


@dataclass(frozen=True)
class SpeechAudio:
    audio: bytes
    content_type: str
    cached: bool


def split_sentences(text: str) -> list[str]:
    """Split a beat into sentences so each can be synthesised and played in turn."""
    return [part.strip() for part in SENTENCE_END.split(" ".join(text.split())) if part.strip()]


def to_ssml(sentence: str, voice: VoiceStyle) -> str:
    """Wrap one sentence in pacing markup for this voice. Adds pauses, never words."""
    # Mark pauses on the raw text, then escape, so the ";" in "&amp;" is never a pause.
    marked = CLAUSE_PAUSE.sub(lambda match: f"{match.group(1)}{PAUSE_MARK} ", sentence.strip())
    paced = escape(" ".join(marked.split())).replace(
        PAUSE_MARK, f'<break time="{voice.comma_pause_ms}ms"/>'
    )
    return (
        f'<speak><prosody rate="{voice.rate_percent}%">{paced}</prosody>'
        f'<break time="{voice.sentence_pause_ms}ms"/></speak>'
    )


def spoken_words(ssml: str) -> str:
    """The words a listener hears, with markup removed; used to prove nothing was added."""
    text = re.sub(r"<[^>]+>", "", ssml)
    for entity, char in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">")):
        text = text.replace(entity, char)
    return " ".join(text.split())


class SpeechBackend(Protocol):
    name: str

    def synthesize(self, ssml: str) -> bytes: ...


class MockSpeech:
    """No audio: tells the front end to use browser speech. The default, needing no AWS."""

    name = "mock"

    def synthesize(self, ssml: str) -> bytes:
        raise SpeechUnavailable("Speech backend is mock.")


class PollySpeech:
    """Amazon Polly, with a small bounded retry for throttling."""

    name = "polly"

    def __init__(self, client: Any | None = None, sleep: Any = time.sleep) -> None:
        self._sleep = sleep
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "polly",
                region_name=settings.POLLY_REGION,
                config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 0}),
            )
        self.client = client

    def synthesize(self, ssml: str) -> bytes:
        for attempt in range(settings.SPEECH_RETRIES + 1):
            try:
                response = self.client.synthesize_speech(
                    Text=ssml,
                    TextType="ssml",
                    OutputFormat="mp3",
                    VoiceId=settings.POLLY_VOICE_ID,
                    Engine=settings.POLLY_ENGINE,
                )
                return response["AudioStream"].read()
            except Exception as error:
                code = getattr(error, "response", {}).get("Error", {}).get("Code", "")
                if code not in RETRYABLE or attempt == settings.SPEECH_RETRIES:
                    raise SpeechUnavailable(f"Polly failed: {code or error}") from error
                self._sleep((2**attempt) * 0.4 + random.uniform(0, 0.2))
        raise SpeechUnavailable("Polly failed after retries.")  # pragma: no cover


class AudioCache(Protocol):
    def get(self, key: str) -> bytes | None: ...

    def set(self, key: str, value: bytes, ex: int) -> object: ...


def configured_backend() -> SpeechBackend:
    if settings.SPEECH_BACKEND == "polly":
        return PollySpeech()
    return MockSpeech()


def _default_cache() -> AudioCache:
    return redis.Redis.from_url(settings.REDIS_URL)


def cache_key(backend_name: str, voice: VoiceStyle, text: str) -> str:
    identity = "|".join(
        (backend_name, settings.POLLY_VOICE_ID, settings.POLLY_ENGINE, voice.key, text)
    )
    return "greeo:speech:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def synthesize_sentence(
    text: str,
    voice_key: str | None = None,
    *,
    backend: SpeechBackend | None = None,
    cache: AudioCache | None = None,
) -> SpeechAudio | None:
    """Audio for one sentence, cached by text and voice. None means use browser speech."""
    text = " ".join(text.split())
    if not text or len(text) > MAX_CHUNK_CHARS:
        raise ValueError(f"Send one sentence of at most {MAX_CHUNK_CHARS} characters.")
    voice = VOICE_STYLES.get(voice_key or "", VOICE_STYLES["moonlight_elder"])
    backend = backend or configured_backend()
    if backend.name == "mock":
        return None
    cache = cache or _default_cache()
    key = cache_key(backend.name, voice, text)
    try:
        stored = cache.get(key)
    except redis.RedisError:
        stored = None
    if stored:
        return SpeechAudio(audio=stored, content_type="audio/mpeg", cached=True)
    try:
        audio = backend.synthesize(to_ssml(text, voice))
    except SpeechUnavailable:
        logger.warning("Speech unavailable; the front end will use browser speech.", exc_info=True)
        return None
    try:
        cache.set(key, audio, ex=settings.SPEECH_CACHE_SECONDS)
    except redis.RedisError:
        logger.warning("Could not cache speech audio.", exc_info=True)
    return SpeechAudio(audio=audio, content_type="audio/mpeg", cached=False)
