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

    The number of beats follows the tale's length, and the sentences are divided so the
    longest beat is as short as possible. Problems are reported rather than repaired: a
    sentence over the limit is never cut mid-thought.
    """
    sentences = [s.strip() for s in SENTENCE_BREAK.split(tale.strip()) if s.strip()]
    sizes = [spoken_words(s, spoken_by_slot) for s in sentences]
    problems = [
        f"a sentence has {size} words, over the {MAX_BEAT_WORDS}-word beat limit: {s[:60]}..."
        for s, size in zip(sentences, sizes, strict=True)
        if size > MAX_BEAT_WORDS
    ]
    if len(sentences) < MIN_BEATS:
        problems.append(
            f"the tale has only {len(sentences)} sentences; it needs at least {MIN_BEATS}."
        )
        return [" ".join(sentences)] if sentences else [], problems

    wanted = math.ceil(sum(sizes) / TARGET_BEAT_WORDS)
    count = min(max(wanted, MIN_BEATS), MAX_BEATS, len(sentences))
    groups = balanced_groups(sizes, count)
    texts = [" ".join(sentences[start:end]) for start, end in groups]
    for number, text in enumerate(texts, start=1):
        words = spoken_words(text, spoken_by_slot)
        if words > MAX_BEAT_WORDS:
            problems.append(f"beat {number} has {words} words; the tale is too long for 5 beats.")
    return texts, problems


def balanced_groups(sizes: list[int], count: int) -> list[tuple[int, int]]:
    """Split sizes into `count` contiguous runs minimising the largest run's total.

    A small dynamic programme: best[k][i] is the smallest possible largest run when the
    first i items are split into k runs. Tales have a few dozen sentences at most.
    """
    prefix = [0]
    for size in sizes:
        prefix.append(prefix[-1] + size)
    n = len(sizes)
    infinity = float("inf")
    best = [[infinity] * (n + 1) for _ in range(count + 1)]
    cut = [[0] * (n + 1) for _ in range(count + 1)]
    best[0][0] = 0
    for k in range(1, count + 1):
        for i in range(k, n + 1):
            for j in range(k - 1, i):
                largest = max(best[k - 1][j], prefix[i] - prefix[j])
                if largest < best[k][i]:
                    best[k][i], cut[k][i] = largest, j
    groups, end = [], n
    for k in range(count, 0, -1):
        start = cut[k][end]
        groups.append((start, end))
        end = start
    return groups[::-1]
