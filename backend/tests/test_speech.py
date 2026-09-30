"""Simulator speech: pacing per voice, Polly with retry and cache, browser fallback."""

from __future__ import annotations

import io

import pytest
from apps.simulator.speech import (
    MockSpeech,
    PollySpeech,
    SpeechUnavailable,
    split_sentences,
    spoken_words,
    synthesize_sentence,
    to_ssml,
)
from apps.stories.voices import VOICE_STYLES
from django.test import override_settings

BEAT = (
    "Listen. In Veloria, the Pell River ran wide and cold, and the children crossed it "
    "by canoe. Was it safe? No! Salt & rope held."
)


class ThrottledError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakePolly:
    def __init__(self, failures: list[str] | None = None) -> None:
        self.failures = list(failures or [])
        self.requests: list[dict] = []

    def synthesize_speech(self, **request) -> dict:
        self.requests.append(request)
        if self.failures:
            raise ThrottledError(self.failures.pop(0))
        return {"AudioStream": io.BytesIO(b"SYNTHETIC-MP3")}


class FakeCache:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.expiry: dict[str, int] = {}

    def get(self, key: str) -> bytes | None:
        return self.values.get(key)

    def set(self, key: str, value: bytes, ex: int) -> bool:
        self.values[key], self.expiry[key] = value, ex
        return True


def polly(client: FakePolly) -> PollySpeech:
    return PollySpeech(client=client, sleep=lambda seconds: None)


def test_beats_split_into_sentences_for_sequential_playback() -> None:
    assert split_sentences(BEAT) == [
        "Listen.",
        "In Veloria, the Pell River ran wide and cold, and the children crossed it by canoe.",
        "Was it safe?",
        "No!",
        "Salt & rope held.",
    ]


@pytest.mark.parametrize("voice_key", sorted(VOICE_STYLES))
def test_pacing_markup_changes_rate_and_pauses_but_never_the_words(voice_key: str) -> None:
    voice = VOICE_STYLES[voice_key]

    for sentence in split_sentences(BEAT):
        ssml = to_ssml(sentence, voice)
        assert spoken_words(ssml) == sentence
        assert ssml.startswith(f'<speak><prosody rate="{voice.rate_percent}%">')
        assert f'<break time="{voice.sentence_pause_ms}ms"/></speak>' in ssml
        assert "pitch" not in ssml  # neural voices do not support pitch changes


def test_markup_escapes_text_and_adds_clause_pauses() -> None:
    ssml = to_ssml("Salt & rope, then <stone>.", VOICE_STYLES["moonlight_elder"])

    assert 'Salt &amp; rope,<break time="120ms"/> then' in ssml
    assert ssml.count("<break") == 2  # one clause pause, one sentence pause
    assert "&lt;stone&gt;" in ssml


def test_mock_backend_means_browser_speech() -> None:
    assert synthesize_sentence("Listen.", backend=MockSpeech(), cache=FakeCache()) is None


@override_settings(POLLY_VOICE_ID="TestVoice", POLLY_ENGINE="neural", SPEECH_RETRIES=2)
def test_polly_is_called_with_ssml_and_the_result_is_cached() -> None:
    client, cache = FakePolly(), FakeCache()

    first = synthesize_sentence("Listen.", "village_fire", backend=polly(client), cache=cache)
    second = synthesize_sentence("Listen.", "village_fire", backend=polly(client), cache=cache)

    assert (first.audio, first.content_type, first.cached) == (
        b"SYNTHETIC-MP3",
        "audio/mpeg",
        False,
    )
    assert second.cached is True and len(client.requests) == 1
    request = client.requests[0]
    assert request["TextType"] == "ssml" and request["OutputFormat"] == "mp3"
    assert (request["VoiceId"], request["Engine"]) == ("TestVoice", "neural")
    assert 'rate="97%"' in request["Text"]
    assert set(cache.expiry.values()) == {86400}


def test_a_different_voice_is_cached_separately() -> None:
    client, cache = FakePolly(), FakeCache()

    synthesize_sentence("Listen.", "village_fire", backend=polly(client), cache=cache)
    synthesize_sentence("Listen.", "moonlight_elder", backend=polly(client), cache=cache)

    assert len(client.requests) == 2


@override_settings(SPEECH_RETRIES=2)
def test_throttling_is_retried_then_succeeds() -> None:
    client = FakePolly(failures=["ThrottlingException"])

    audio = synthesize_sentence("Listen.", backend=polly(client), cache=FakeCache())

    assert audio.audio == b"SYNTHETIC-MP3" and len(client.requests) == 2


@override_settings(SPEECH_RETRIES=1)
def test_failures_fall_back_to_browser_speech_without_raising() -> None:
    always_throttled = FakePolly(failures=["ThrottlingException"] * 5)
    denied = FakePolly(failures=["AccessDeniedException"])

    assert (
        synthesize_sentence("Listen.", backend=polly(always_throttled), cache=FakeCache()) is None
    )
    assert len(always_throttled.requests) == 2
    assert synthesize_sentence("Listen.", backend=polly(denied), cache=FakeCache()) is None
    assert len(denied.requests) == 1  # not retryable

    with pytest.raises(SpeechUnavailable):
        polly(FakePolly(failures=["AccessDeniedException"])).synthesize("<speak/>")


def test_only_one_sentence_sized_chunk_is_accepted() -> None:
    with pytest.raises(ValueError, match="at most 600 characters"):
        synthesize_sentence("word " * 200, backend=MockSpeech())
    with pytest.raises(ValueError):
        synthesize_sentence("   ", backend=MockSpeech())
