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


class LayerStep(BaseModel):
    key: str
    label: str
    state: str = Field(description="current, heard, or ahead")


class LayerProgress(BaseModel):
    """Which layers this story has and where the listener is, for the card's progress strip."""

    current: str
    steps: list[LayerStep]


class StoryEnvelope(Envelope):
    """Fields every story card needs: which story, its title and the listener's progress."""

    story_id: str
    title: str
    progress: LayerProgress


class StoryListing(BaseModel):
    story_id: str
    title: str
    region: str


class StoryList(Envelope):
    stories: list[StoryListing]
    page: int
    has_more: bool


class HelpResult(Envelope):
    """What Greeo can do, fitted to where the listener is."""

    abilities: list[str] = Field(description="Short labels for what Greeo can do.")
    current_story_id: str | None = Field(
        default=None, description="The story the listener can continue, if any."
    )
    current_title: str | None = None


class ProverbFlag(BaseModel):
    slot: str
    culture: str
    spoken_form: str = Field(description="The proverb as spoken in the beat, for highlighting.")


class ProverbDetail(BaseModel):
    slot: str
    spoken_form: str
    original_text: str
    language: str
    culture: str
    meaning: str
    source_citation: str
    verification_status: str


class TaleBeat(StoryEnvelope):
    beat: int
    beats_total: int
    has_more: bool
    tone_served: str
    voice_style: str = Field(
        description="Key of the storyteller voice, for hosts that pace speech."
    )
    voice_name: str
    text: str = Field(description="The beat exactly as written, proverb included, for cards.")
    proverbs_used: list[ProverbFlag]


class ClosingThought(StoryEnvelope):
    closing_kind: str = Field(description="moral, reflection, or none")
    text: str
    proverb_note: str
    proverbs: list[ProverbDetail] = Field(default_factory=list)


class ProverbExplanation(StoryEnvelope):
    proverbs: list[ProverbDetail] = Field(
        default_factory=list, description="Every proverb in this telling, for the card."
    )
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


class FactList(StoryEnvelope):
    facts: list[FactItem]


class ContextItem(BaseModel):
    kind: str
    label: str
    text: str
    sources: list[SourceRef]


class ContextList(StoryEnvelope):
    context: list[ContextItem]


class PerspectiveItem(BaseModel):
    label: str
    summary: str
    sources: list[SourceRef]


class PerspectiveList(StoryEnvelope):
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


class SourceList(StoryEnvelope):
    sources: list[SourceCard]


class SaveResult(Envelope):
    story_id: str
    title: str
    saved: bool


class SavedStory(BaseModel):
    story_id: str
    title: str
    saved: bool
    tone: str
    last_beat: int
    beats_total: int
    tale_completed: bool
    resume_hint: str


class SavedList(Envelope):
    stories: list[SavedStory]


class PreferencesResult(Envelope):
    tone: str | None
    regions: list[str]
    topics: list[str]
    reset: bool
