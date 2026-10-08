"""Output shapes for the editorial prompts, validated before anything is used.

The writer's shape lives in composition.py next to the code that turns it into beats.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator


class Fact(BaseModel):
    id: str
    text: str


class ContextNote(BaseModel):
    """Background the article itself gives: what led here, why it matters, what follows."""

    kind: Literal["background", "why_it_matters", "consequence"]
    text: str


# A note that talks about its source instead of reporting it.
ABOUT_THE_SOURCE = re.compile(
    r"\b(the article|the report|not (specified|stated|clear|mentioned))\b", re.IGNORECASE
)
# A guess, unless someone in the article is the one saying it.
GUESS = re.compile(r"\b(suggests?|may|might|could|likely|possibly|perhaps)\b", re.IGNORECASE)
ATTRIBUTED = re.compile(
    r"\b(says?|said|according to|warns?|warned|expects?|plans?)\b", re.IGNORECASE
)


def is_guess(text: str) -> bool:
    return bool(
        ABOUT_THE_SOURCE.search(text) or (GUESS.search(text) and not ATTRIBUTED.search(text))
    )


class PerspectiveNote(BaseModel):
    """One side's view as the article reports it, attributed to that side."""

    label: str
    summary: str


class EstablishedFacts(BaseModel):
    """establish_facts: what an article establishes, in order, with its context and views."""

    title: str = ""
    reasoning: str
    facts: list[Fact]
    context: list[ContextNote] = []
    perspectives: list[PerspectiveNote] = []
    themes: list[str]
    tone_class: Literal["neutral", "sensitive"]
    tone_class_reason: str

    @field_validator("context")
    @classmethod
    def drop_guesses(cls, value: list[ContextNote]) -> list[ContextNote]:
        """Context is said aloud as reported fact, so a note that guesses is dropped."""
        return [note for note in value if not is_guess(note.text)]

    @field_validator("facts", mode="before")
    @classmethod
    def number_plain_strings(cls, value: Any) -> Any:
        """Small models sometimes return facts as plain strings; number them in order."""
        if isinstance(value, list):
            return [
                {"id": f"F{n}", "text": item} if isinstance(item, str) else item
                for n, item in enumerate(value, start=1)
            ]
        return value


class ProverbPick(BaseModel):
    id: str
    why: str


class ProverbRanking(BaseModel):
    """rerank_proverb: the best-fitting proverb by meaning, and up to two alternates."""

    reasoning: str
    best: ProverbPick | None = None
    alternates: list[ProverbPick] = []


class TellingIssue(BaseModel):
    quote: str
    problem: str


class TellingCheck(BaseModel):
    """check_telling: what a tale says that its facts and context do not support."""

    reasoning: str
    issues: list[TellingIssue] = []
