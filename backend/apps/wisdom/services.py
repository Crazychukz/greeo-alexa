"""Rules-first proverb retrieval. No LLM call belongs in this module yet."""

from __future__ import annotations

from dataclasses import dataclass

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


def rerank_with_llm(candidates: list[Proverb], story: Story) -> list[ProverbSuggestion]:
    """Reserve the controlled candidate reranking hook for Phase 6B."""
    raise NotImplementedError("LLM proverb reranking is introduced in Phase 6B.")
