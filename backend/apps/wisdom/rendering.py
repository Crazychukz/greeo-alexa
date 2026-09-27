"""Substitute verified proverb text into telling templates. No LLM is involved.

Writers (human or model) only ever place slot markers such as ``{{P1}}``. This module
is the single place where a marker becomes words, so the spoken proverb is always the
exact ``spoken_form`` of a verified corpus entry.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.stories.models import TellingBeat

SLOT_PATTERN = re.compile(r"\{\{(P[1-9][0-9]*)\}\}")


class RenderingError(Exception):
    """Raised when a template cannot be rendered safely."""


@dataclass(frozen=True)
class ProverbReference:
    """What a card needs to explain a proverb heard in a beat, including where it is from."""

    slot: str
    proverb_id: str
    spoken_form: str
    original_text: str
    language: str
    culture: str
    meaning_note: str
    source_citation: str
    verification_status: str


@dataclass(frozen=True)
class RenderedBeat:
    order: int
    text: str
    proverbs: tuple[ProverbReference, ...]


def find_slots(template: str) -> list[str]:
    """Return slot names in the order they appear, including repeats."""
    return SLOT_PATTERN.findall(template)


def fill_slots(template: str, spoken_by_slot: Mapping[str, str]) -> str:
    """Replace every slot with its spoken text, refusing unknown slots."""

    def replace(match: re.Match[str]) -> str:
        slot = match.group(1)
        if slot not in spoken_by_slot:
            raise RenderingError(f"Unknown proverb slot {{{{{slot}}}}}.")
        return spoken_by_slot[slot]

    return SLOT_PATTERN.sub(replace, template)


def render_beat(beat: TellingBeat) -> RenderedBeat:
    """Render one stored beat, re-checking that every proverb is still servable.

    The check repeats at render time because a proverb can be disputed after a
    telling was published; an unverified proverb must never be spoken.
    """
    links = {link.slot: link for link in beat.telling.proverb_links.select_related("proverb")}
    used = find_slots(beat.text_template)
    references = []
    for slot in used:
        link = links.get(slot)
        if link is None:
            raise RenderingError(f"Beat {beat.order} uses unmapped slot {{{{{slot}}}}}.")
        if not link.proverb_is_servable:
            raise RenderingError(f"Proverb {link.proverb_id} in slot {slot} is not servable.")
        proverb = link.proverb
        references.append(
            ProverbReference(
                slot=slot,
                proverb_id=proverb.id,
                spoken_form=proverb.spoken_form,
                original_text=proverb.original_text,
                language=proverb.language,
                culture=proverb.culture,
                meaning_note=proverb.meaning_note,
                source_citation=proverb.source_citation,
                verification_status=proverb.verification_status,
            )
        )
    spoken = {reference.slot: reference.spoken_form for reference in references}
    return RenderedBeat(
        order=beat.order,
        text=fill_slots(beat.text_template, spoken),
        proverbs=tuple(references),
    )
