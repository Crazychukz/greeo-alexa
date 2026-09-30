"""The voice gate: word limits, vocabulary, options, pagination and friendly errors."""

from __future__ import annotations

import pytest
from apps.core.speech import forbidden_words
from apps.mcp_server.schemas import Envelope
from apps.mcp_server.voice import (
    BeatTooLongError,
    VoiceSafetyError,
    assert_voice_safe,
    finalize,
    friendly_error,
    paginate,
    truncate_spoken,
    word_count,
)


def test_truncate_keeps_whole_sentences_within_the_limit() -> None:
    text = " ".join(f"Sentence number {n} has five words." for n in range(1, 30))

    short = truncate_spoken(text, max_words=20)

    assert word_count(short) <= 20
    assert short.endswith("words.")
    assert truncate_spoken("Short and sweet.") == "Short and sweet."


def test_truncate_cuts_one_long_sentence_at_a_word_boundary() -> None:
    text = " ".join(["word"] * 100) + "."

    short = truncate_spoken(text, max_words=10)

    assert word_count(short) == 10
    assert short.endswith("…")


def test_paginate_returns_items_has_more_and_a_hint() -> None:
    items = list(range(12))

    first, third, beyond = paginate(items, 1), paginate(items, 3), paginate(items, 4)

    assert (first.items, first.has_more, first.next_page_hint) == (
        [0, 1, 2, 3, 4],
        True,
        "more stories",
    )
    assert (third.items, third.has_more, third.next_page_hint) == ([10, 11], False, None)
    assert beyond.items == []


def test_friendly_errors_are_plain_words_with_a_next_step() -> None:
    for kind in ("unknown_story", "which_story", "needs_account", "invalid_request", "unexpected"):
        spoken, next_options = friendly_error(kind)
        assert_voice_safe(spoken)
        assert next_options
    assert friendly_error("not_a_kind") == friendly_error("unexpected")
    assert friendly_error("unknown_story", hint="Custom.")[0] == "Custom."


@pytest.mark.parametrize(
    "text",
    [
        "The tool failed",
        "JSON payload",
        "An API call",
        "error code 5",
        "an exception",
        "the traceback",
        "story_id st_1",
        "undefined value",
        "null",
    ],
)
def test_forbidden_vocabulary_is_caught(text: str) -> None:
    with pytest.raises(VoiceSafetyError):
        assert_voice_safe(text)


def test_forbidden_vocabulary_matches_whole_words_only() -> None:
    assert forbidden_words("Toolmakers and rapid nullahs are fine") == []
    assert forbidden_words("A TOOL, a Tool and a tool") == ["tool"]


def test_finalize_trims_speech_limits_options_and_never_returns_silence() -> None:
    # model_construct skips validation, standing in for a handler that built a bad reply.
    long = Envelope.model_construct(
        spoken=" ".join(f"Sentence {n} is here." for n in range(40)),
        next_options=["a", "b", "a", "c", "d", "e", "f"],
    )

    result = finalize(long)

    assert word_count(result.spoken) <= 75
    assert result.next_options == ["a", "b", "c", "d", "e"]
    assert finalize(Envelope(spoken="   ")).spoken == "What would you like to hear next?"


def test_finalize_never_shortens_a_beat() -> None:
    beat = Envelope(spoken=" ".join(["word"] * 80))

    with pytest.raises(BeatTooLongError):
        finalize(beat, verbatim=True)


def test_finalize_rejects_forbidden_words_in_speech_and_options() -> None:
    with pytest.raises(VoiceSafetyError):
        finalize(Envelope(spoken="Here is your JSON."))
    with pytest.raises(VoiceSafetyError):
        finalize(Envelope(spoken="Fine.", next_options=["call the tool"]))
