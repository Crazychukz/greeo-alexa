"""Output shapes for the editorial prompts, validated before anything is used.

The writer's shape lives in composition.py next to the code that turns it into beats.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, field_validator


class Fact(BaseModel):
    id: str
    text: str


class EstablishedFacts(BaseModel):
    """establish_facts: what an article establishes, in order."""

    reasoning: str
    facts: list[Fact]
    themes: list[str]
    tone_class: Literal["neutral", "sensitive"]
    tone_class_reason: str

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
