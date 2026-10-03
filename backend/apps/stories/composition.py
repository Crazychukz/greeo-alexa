"""Turn a model's whole tale into spoken beats. No LLM is involved.

A tale is written whole, the way a storyteller tells it, with proverb slots such as
``{{P1}}`` woven into its sentences. Alexa+ speaks at most 75 words a turn, so code then
splits the tale into 3-5 beats at sentence ends. Rendering substitutes each slot with
the corpus wording, exactly as for curated tellings.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

from apps.wisdom.rendering import SLOT_PATTERN, find_slots

MAX_BEAT_WORDS = 75
MIN_BEATS = 3
MAX_BEATS = 5
# A beat this long or more is comfortable; the split aims a little under the limit.
TARGET_BEAT_WORDS = 65
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
WORD = re.compile(r"[A-Za-z0-9À-ɏ][\w'’À-ɏ-]*")


class TellingDraft(BaseModel):
    """What the writer model returns for one tone."""

    tale: str
    proverbs_used: list[str] = Field(default_factory=list)
    closing_kind: Literal["moral", "reflection", "none"]
    closing_text: str = ""


def spoken_words(text: str, spoken_by_slot: Mapping[str, str]) -> int:
    """Words as heard: each slot counts as its proverb's words."""
    heard = SLOT_PATTERN.sub(lambda m: f" {spoken_by_slot.get(m.group(1), '')} ", text)
    return len(WORD.findall(heard))


def used_slots(draft: TellingDraft, offered: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """The slots the tale really uses, and problems with how it uses them."""
    problems = []
    in_tale = find_slots(draft.tale)
    for slot in sorted(set(in_tale)):
        if slot not in offered:
            problems.append(f"the tale uses {{{{{slot}}}}}, which was not offered.")
        elif in_tale.count(slot) > 1:
            problems.append(f"the tale uses {{{{{slot}}}}} {in_tale.count(slot)} times; once only.")
    for slot in draft.proverbs_used:
        if slot not in in_tale:
            problems.append(f"{slot} is listed as used but does not appear in the tale.")
    return {slot: offered[slot] for slot in in_tale if slot in offered}, problems


def split_tale(tale: str, spoken_by_slot: Mapping[str, str]) -> tuple[list[str], list[str]]:
    """3-5 beats of at most 75 spoken words, split only between sentences.

    Beats are balanced toward equal length so no beat is a stub. Problems are reported
    rather than repaired: a sentence over the limit is never cut mid-thought.
    """
    sentences = [s.strip() for s in SENTENCE_BREAK.split(tale.strip()) if s.strip()]
    sizes = [spoken_words(s, spoken_by_slot) for s in sentences]
    problems = [
        f"a sentence has {size} words, over the {MAX_BEAT_WORDS}-word beat limit: {s[:60]}..."
        for s, size in zip(sentences, sizes, strict=True)
        if size > MAX_BEAT_WORDS
    ]
    total = sum(sizes)
    count = min(max(math.ceil(total / TARGET_BEAT_WORDS), MIN_BEATS), MAX_BEATS)
    count = min(count, len(sentences))

    beats: list[list[str]] = [[]]
    for index, (sentence, size) in enumerate(zip(sentences, sizes, strict=True)):
        remaining_words = sum(sizes[index:])
        beats_left = count - len(beats)
        current = sum(spoken_words(s, spoken_by_slot) for s in beats[-1])
        fair_share = (remaining_words + current) / (beats_left + 1)
        start_new = (
            beats[-1]
            and beats_left > 0
            and (current + size > MAX_BEAT_WORDS or current >= fair_share)
        )
        if start_new:
            beats.append([])
        beats[-1].append(sentence)

    texts = [" ".join(beat) for beat in beats]
    for number, text in enumerate(texts, start=1):
        words = spoken_words(text, spoken_by_slot)
        if words > MAX_BEAT_WORDS:
            problems.append(f"beat {number} has {words} words; the tale is too long for 5 beats.")
    if len(texts) < MIN_BEATS:
        problems.append(f"the tale has only {len(texts)} sentences; it needs at least 3 beats.")
    return texts, problems
