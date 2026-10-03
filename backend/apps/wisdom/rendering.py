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


# A slot with any sentence punctuation the template puts straight after it.
SLOT_WITH_STOP = re.compile(r"\{\{(P[1-9][0-9]*)\}\}([.!?,;])?")
TERMINAL = (".", "!", "?")


def fill_slots(template: str, spoken_by_slot: Mapping[str, str]) -> str:
    """Replace every slot with its spoken text, refusing unknown slots.

    Punctuation is merged, never doubled: a proverb that already ends a sentence
    absorbs the template's own full stop, and a proverb that ends the beat without
    punctuation gets one. The proverb's words are never changed.
    """

    def replace(match: re.Match[str]) -> str:
        slot, stop = match.group(1), match.group(2)
        if slot not in spoken_by_slot:
            raise RenderingError(f"Unknown proverb slot {{{{{slot}}}}}.")
        spoken = spoken_by_slot[slot].rstrip()
        if mid_sentence(template[: match.start()]):
            spoken = lower_first_word(spoken)
        if stop in {",", ";"}:
            # The sentence goes on: a closing full stop gives way to the comma.
            return (spoken[:-1] if spoken.endswith(".") else spoken) + stop
        if spoken.endswith(TERMINAL):
            return spoken
        if stop:
            return spoken + stop
        at_end = not template[match.end() :].strip()
        return spoken + "." if at_end else spoken

    return SLOT_WITH_STOP.sub(replace, template)


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


# Opening words that are ordinary words, safe to lower-case when a proverb is woven into
# a sentence ("She knew that a person who..."). Any other first word may be a name.
COMMON_FIRST_WORDS = frozenset(
    "a an the when if no none one every whoever he she it they you we what where who "
    "though although even do don't never all those there however until money".split()
)


def mid_sentence(before: str) -> bool:
    """True when the slot continues a sentence rather than starting one."""
    text = before.rstrip()
    return bool(text) and text[-1] not in ".!?:\n\"'“”"


def lower_first_word(spoken: str) -> str:
    """Lower-case only the first letter, and only of a common word; words never change."""
    first = spoken.split(" ", 1)[0]
    if first.lower().rstrip(",;") in COMMON_FIRST_WORDS and first[:1].isupper():
        return spoken[:1].lower() + spoken[1:]
    return spoken
