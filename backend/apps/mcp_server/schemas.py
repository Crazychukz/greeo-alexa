"""Structured tool outputs. Each model becomes the tool's published outputSchema.

Every result carries `spoken` (plain text written for voice) and `next_options` (at
most five short labels). The same data drives voice and cards, so they cannot disagree.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_OPTIONS = 5


class Envelope(BaseModel):
    spoken: str = Field(description="Plain text written to be spoken aloud as written.")
    next_options: list[str] = Field(
        default_factory=list,
        max_length=MAX_OPTIONS,
        description="Up to five short things the listener can ask for next.",
    )


class StoryListing(BaseModel):
    story_id: str
    title: str
    region: str


class StoryList(Envelope):
    stories: list[StoryListing]
    page: int
    has_more: bool


class ProverbFlag(BaseModel):
    slot: str
    culture: str


class TaleBeat(Envelope):
    story_id: str
    title: str
    beat: int
    beats_total: int
    has_more: bool
    tone_served: str
    text: str = Field(description="The beat exactly as written, proverb included, for cards.")
    proverbs_used: list[ProverbFlag]


class ClosingThought(Envelope):
    story_id: str
    closing_kind: str = Field(description="moral, reflection, or none")
    text: str
    proverb_note: str


class ProverbExplanation(Envelope):
    story_id: str
    has_proverb: bool
    which: int
    proverbs_total: int
    spoken_form: str = ""
    original_text: str = ""
    language: str = ""
    culture: str = ""
    meaning: str = ""
    source_citation: str = ""
    verification_status: str = ""


class SourceRef(BaseModel):
    publisher: str
    date: str


class FactItem(BaseModel):
    text: str
    sources: list[SourceRef]


class FactList(Envelope):
    story_id: str
    facts: list[FactItem]


class ContextItem(BaseModel):
    kind: str
    label: str
    text: str
    sources: list[SourceRef]


class ContextList(Envelope):
    story_id: str
    context: list[ContextItem]


class PerspectiveItem(BaseModel):
    label: str
    summary: str
    sources: list[SourceRef]


class PerspectiveList(Envelope):
    story_id: str
    perspectives: list[PerspectiveItem]


class SourceCard(BaseModel):
    publisher: str
    headline: str
    date: str
    supports: list[str] = Field(
        description="Which layers this source backs: facts, context, perspectives."
    )
    url: str | None = Field(
        default=None, description="Only present when INCLUDE_SOURCE_URLS is on."
    )


class SourceList(Envelope):
    story_id: str
    sources: list[SourceCard]
