"""The voice-quality gate: every tool reply passes through finalize() before it leaves.

Alexa+ rules enforced here: at most 75 spoken words (about 30 seconds), at most five
options, no technical vocabulary, never an empty reply, and every error in plain words
with a next step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from apps.core.speech import forbidden_words

from .schemas import MAX_OPTIONS, Envelope

MAX_SPOKEN_WORDS = 75
WORD = re.compile(r"\S+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
FALLBACK_SPOKEN = "What would you like to hear next?"


class VoiceSafetyError(ValueError):
    """Spoken text contains words no listener should hear. A bug or a data error."""


class BeatTooLongError(ValueError):
    """A tale beat exceeds the word limit. Beats are validated at load, so this is data drift."""


def word_count(text: str) -> int:
    return len(WORD.findall(text))


def truncate_spoken(text: str, max_words: int = MAX_SPOKEN_WORDS) -> str:
    """Keep whole sentences within the limit; cut a single long sentence at a word boundary.

    Never used on tale beats: cutting a beat would change a checked telling.
    """
    text = " ".join(text.split())
    if word_count(text) <= max_words:
        return text
    kept: list[str] = []
    for sentence in SENTENCE_END.split(text):
        if word_count(" ".join([*kept, sentence])) > max_words:
            break
        kept.append(sentence)
    if kept:
        return " ".join(kept)
    words = WORD.findall(text)[:max_words]
    return " ".join(words).rstrip(",;:") + "…"


def join_within(sentences: list[str], *, more: str, max_words: int = MAX_SPOKEN_WORDS) -> str:
    """Join whole sentences until the word limit, then offer the rest instead of cutting."""
    chosen: list[str] = []
    used = word_count(more)
    for sentence in sentences:
        words = word_count(sentence)
        if chosen and used + words > max_words:
            return " ".join([*chosen, more]).strip()
        chosen.append(sentence)
        used += words
    return " ".join(chosen).strip()


@dataclass(frozen=True)
class Page[ItemT]:
    items: list[ItemT]
    page: int
    has_more: bool
    next_page_hint: str | None


def paginate[ItemT](items: list[ItemT], page: int, size: int = MAX_OPTIONS) -> Page[ItemT]:
    """At most `size` items per page, with a spoken hint when more remain."""
    page = max(page, 1)
    start = (page - 1) * size
    chunk = items[start : start + size]
    has_more = start + size < len(items)
    return Page(chunk, page, has_more, "more stories" if has_more else None)


FRIENDLY_ERRORS: dict[str, tuple[str, tuple[str, ...]]] = {
    "unknown_story": (
        "I couldn't find that story. You can ask for today's stories, or search for a topic.",
        ("today's stories",),
    ),
    "which_story": (
        "Which story would you like? You can ask for today's stories, or search for a topic.",
        ("today's stories",),
    ),
    "needs_account": (
        "To save stories and remember where you stopped, link your account in the Alexa app. "
        "You can still hear any story now.",
        ("today's stories",),
    ),
    "invalid_request": (
        "I couldn't quite do that. You can ask for today's stories, or search for a topic.",
        ("today's stories",),
    ),
    "unexpected": (
        "Something went wrong on my side. Please try again in a moment, or ask for another story.",
        ("today's stories",),
    ),
}


def friendly_error(kind: str, hint: str | None = None) -> tuple[str, list[str]]:
    """Plain-language message and next options for a known problem; `hint` replaces the text."""
    spoken, next_options = FRIENDLY_ERRORS.get(kind, FRIENDLY_ERRORS["unexpected"])
    return hint or spoken, list(next_options)


def options(*labels: str | None) -> list[str]:
    """Distinct, non-empty labels, at most five, in the order given."""
    return list(dict.fromkeys(label for label in labels if label))[:MAX_OPTIONS]


def assert_voice_safe(text: str) -> None:
    found = forbidden_words(text)
    if found:
        raise VoiceSafetyError(f"Spoken text contains {', '.join(found)}: {text[:120]!r}")


def finalize[EnvelopeT: Envelope](result: EnvelopeT, *, verbatim: bool = False) -> EnvelopeT:
    """The single gate every reply passes: length, vocabulary, options, non-empty speech.

    `verbatim` marks tale beats, which are never shortened: a beat over the limit is a
    data error and fails loudly instead.
    """
    spoken = " ".join(result.spoken.split()) or FALLBACK_SPOKEN
    if word_count(spoken) > MAX_SPOKEN_WORDS:
        if verbatim:
            raise BeatTooLongError(f"Beat has {word_count(spoken)} words: {spoken[:80]!r}")
        spoken = truncate_spoken(spoken)
    assert_voice_safe(spoken)
    next_options = options(*result.next_options)
    for label in next_options:
        assert_voice_safe(label)
    return result.model_copy(update={"spoken": spoken, "next_options": next_options})


def human_date(value: datetime | None) -> str:
    """A spoken-friendly date such as 12 March 2026."""
    return f"{value.day} {value:%B %Y}" if value else "an unknown date"


ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def spoken_dates(text: str) -> str:
    """2026-10-07 becomes 7 October 2026: facts are read aloud, and shown the same way."""

    def readable(match: re.Match[str]) -> str:
        try:
            return human_date(datetime(int(match[1]), int(match[2]), int(match[3])))
        except ValueError:
            return match[0]  # not a real date (a version number, say): leave it

    return ISO_DATE.sub(readable, text)
