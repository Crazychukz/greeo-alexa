"""Proverb retrieval: rules-first candidates, and choice by meaning across the corpus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.llm.client import LLMGateway
from apps.stories.drafts import ProverbRanking
from apps.stories.models import Story

from .models import Proverb


@dataclass(frozen=True)
class ProverbSuggestion:
    proverb: Proverb | None
    role: str | None
    reason_code: str


def candidates_for_story(themes: list[str], tone_class: str, limit: int = 8) -> list[Proverb]:
    """Return deterministic verified candidates, or none for sensitive stories."""
    if tone_class == Story.ToneClass.SENSITIVE or limit <= 0:
        return []
    requested_themes = set(themes)
    candidates = list(Proverb.objects.servable())
    candidates.sort(key=lambda proverb: (-len(requested_themes & set(proverb.themes)), proverb.id))
    return candidates[:limit]


def pick_proverbs(story: Story, max_count: int = 2) -> list[ProverbSuggestion]:
    """Select at most two corpus entries using transparent rules before any future rerank."""
    if story.tone_class == Story.ToneClass.SENSITIVE:
        return [ProverbSuggestion(proverb=None, role=None, reason_code="sensitive_story")]
    candidates = candidates_for_story(story.themes, story.tone_class, limit=max_count)
    if not candidates:
        return [ProverbSuggestion(proverb=None, role=None, reason_code="no_candidates")]
    return [
        ProverbSuggestion(
            proverb=proverb,
            role="opening" if index == 0 else "turn",
            reason_code="matched",
        )
        for index, proverb in enumerate(candidates)
    ]


@dataclass(frozen=True)
class ChosenProverb:
    proverb: Proverb
    why: str


def choose_proverbs(
    facts: list[dict[str, str]], tone_class: str, gateway: Any | None = None
) -> tuple[list[ChosenProverb], str]:
    """Up to three proverbs chosen by meaning from the whole servable corpus.

    The model reads every proverb's meaning, as a storyteller would, instead of a short
    list pre-filtered by theme keywords (most imported proverbs have no themes). It
    only returns ids; unknown ids are dropped, so it can never introduce a proverb.
    Returns the choices and the model's reasoning, for the editor.
    """
    if tone_class == Story.ToneClass.SENSITIVE:
        return [], "Sensitive story: no proverbs."
    pool = {p.id: p for p in Proverb.objects.servable()}
    if not pool:
        return [], "No servable proverbs."
    ranking = (gateway or LLMGateway()).generate_json(
        "rerank_proverb",
        {"facts": facts, "proverbs": [proverb_for_prompt(p) for p in pool.values()]},
        ProverbRanking,
    )
    picks = [ranking.best, *ranking.alternates] if ranking.best else list(ranking.alternates)
    chosen, seen = [], set()
    for pick in picks:
        if pick and pick.id in pool and pick.id not in seen:
            seen.add(pick.id)
            chosen.append(ChosenProverb(proverb=pool[pick.id], why=pick.why))
    return chosen[:3], ranking.reasoning


def proverb_for_prompt(proverb: Proverb) -> dict[str, str]:
    """What the chooser and the writer see: wording, meaning and people, never a source."""
    return {
        "id": proverb.id,
        "text": proverb.spoken_form,
        "meaning": proverb.meaning_note,
        "culture": proverb.culture,
    }
