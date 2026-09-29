"""Small helpers that keep spoken text within Alexa+ limits.

Phase 9 extends this module with the finalize() gate; these are the pieces the Phase 8
tools already need.
"""

from __future__ import annotations

import re
from datetime import datetime

MAX_SPOKEN_WORDS = 75
WORD = re.compile(r"\S+")


def word_count(text: str) -> int:
    return len(WORD.findall(text))


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


def options(*labels: str | None) -> list[str]:
    """Distinct, non-empty labels, at most five, in the order given."""
    return list(dict.fromkeys(label for label in labels if label))[:5]


def human_date(value: datetime | None) -> str:
    """A spoken-friendly date such as 12 March 2026."""
    return f"{value.day} {value:%B %Y}" if value else "an unknown date"
