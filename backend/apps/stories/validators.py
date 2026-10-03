"""Deterministic content checks shared by the curated loader and the later pipeline.

Every function takes plain data and returns a list of human-readable problems, so a
caller can report all problems at once instead of stopping at the first. Nothing here
calls an LLM; judgement that code cannot make belongs to the checker agent (Phase 6B)
and to human curation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from apps.core.speech import forbidden_words
from apps.wisdom.rendering import SLOT_PATTERN, find_slots

MIN_BEATS = 3
MAX_BEATS = 5
MAX_BEAT_WORDS = 75
MAX_CLOSING_CHARS = 200
COPY_GUARD_WORDS = 15

# Double quotation marks in every common typographic form. Straight and curly single
# quotes are allowed because English uses them as apostrophes.
QUOTATION_MARKS = ('"', "“", "”", "„", "«", "»")

# A phrase that attributes wisdom to tradition. It may only introduce a verified
# proverb slot, otherwise Greeo would be presenting its own words as traditional.
ATTRIBUTION_PATTERN = re.compile(
    r"\b(?:an?\s+(?:old\s+)?(?:proverb|saying)|the\s+(?:old\s+)?saying|"
    r"(?:the|our)\s+elders|the\s+ancestors|the\s+old\s+ones)\s+"
    r"(?:says?|said|tells?|told|teach(?:es)?|taught|remind(?:s|ed)?\s+us)\b"
    r"|\bas\s+the\s+(?:old\s+)?saying\s+goes\b",
    re.IGNORECASE,
)
ATTRIBUTION_GAP = re.compile(r"[\s,:;—–-]*")

# Speech or a made-up saying in single quotes: an opening quote after a space or start,
# a closing quote before a space, punctuation or the end. Apostrophes inside words
# (Dangote's, Africans' land) do not match because they lack one of the two edges.
SINGLE_QUOTED = re.compile(r"(?:^|(?<=[\s(:,—–-]))['‘][^'‘’\n]{2,}?[.,!?]?['’](?=[\s.,;:!?)]|$)")

WORD_PATTERN = re.compile(r"[A-Za-z0-9À-ɏ][\w'’À-ɏ-]*")
NUMBER_PATTERN = re.compile(r"\d(?:[\d,.]*\d)?")
SENTENCE_END = ".!?\n"


def word_count(text: str) -> int:
    """Count spoken words; punctuation-only tokens are not words."""
    return len(WORD_PATTERN.findall(text))


def check_beats(beats: list[str], spoken_by_slot: Mapping[str, str]) -> list[str]:
    """Check beat count, length, quotation marks, slots and attribution phrases."""
    problems: list[str] = []
    if not MIN_BEATS <= len(beats) <= MAX_BEATS:
        problems.append(f"needs {MIN_BEATS}-{MAX_BEATS} beats, found {len(beats)}.")

    slot_uses: dict[str, int] = {}
    for index, beat in enumerate(beats, start=1):
        label = f"beat {index}"
        if any(mark in beat for mark in QUOTATION_MARKS) or SINGLE_QUOTED.search(beat):
            problems.append(f"{label} contains a quotation mark; beats may not quote anyone.")
        problems.extend(f"{label} {problem}" for problem in check_storyteller_names(beat))
        leftover = SLOT_PATTERN.sub("", beat)
        if "{{" in leftover or "}}" in leftover:
            problems.append(f"{label} has a malformed slot marker; use {{{{P1}}}} style.")
        for slot in find_slots(beat):
            slot_uses[slot] = slot_uses.get(slot, 0) + 1
            if slot not in spoken_by_slot:
                problems.append(f"{label} uses unknown slot {{{{{slot}}}}}.")
        problems.extend(f"{label} {problem}" for problem in check_attribution(beat))
        words = word_count(_render_known_slots(beat, spoken_by_slot))
        if words > MAX_BEAT_WORDS:
            problems.append(
                f"{label} has {words} words after proverb substitution; limit is {MAX_BEAT_WORDS}."
            )

    for slot in spoken_by_slot:
        uses = slot_uses.get(slot, 0)
        if uses != 1:
            problems.append(f"slot {{{{{slot}}}}} must be used exactly once, found {uses}.")
    return problems


def _render_known_slots(beat: str, spoken_by_slot: Mapping[str, str]) -> str:
    """Render for counting; unknown slots are already reported, so they count as nothing."""
    return SLOT_PATTERN.sub(lambda match: spoken_by_slot.get(match.group(1), ""), beat)


def check_attribution(text: str) -> list[str]:
    """Allow tradition-attributing phrases only directly before a proverb slot."""
    problems = []
    for match in ATTRIBUTION_PATTERN.finditer(text):
        rest = text[match.end() :]
        gap = ATTRIBUTION_GAP.match(rest)
        after = rest[gap.end() if gap else 0 :]
        if not SLOT_PATTERN.match(after):
            problems.append(
                f"uses {match.group(0)!r} without a proverb slot straight after it; "
                "only verified proverbs may be attributed to tradition."
            )
    return problems


def check_proverb_copies(text: str, spoken_by_slot: Mapping[str, str]) -> list[str]:
    """The writer sees proverb wording; it must use the slot, never write the words.

    Writing them out would let a model drift from the verified text unnoticed.
    """
    writer_words = _lower_words(SLOT_PATTERN.sub(" | ", text))
    problems = []
    for slot, spoken in spoken_by_slot.items():
        words = _lower_words(spoken)
        size = min(6, len(words))
        if size >= 3 and _ngrams(words, size) & _ngrams(writer_words, size):
            problems.append(f"writes out the words of {slot}; use {{{{{slot}}}}} instead.")
    return problems


def check_storyteller_names(text: str) -> list[str]:
    """The voice shapes how a tale sounds; the tale never names or describes it."""
    for pattern in storyteller_names():
        if match := pattern.search(text):
            return [f"mentions the storyteller ({match.group(0)!r}); the voice is never named."]
    return []


@lru_cache
def storyteller_names() -> tuple[re.Pattern[str], ...]:
    """Each voice's name as a name (capitalised), and its title noun (the Trickster).

    Lower case is ordinary prose: "a wise judge would weigh both sides" is allowed.
    """
    from apps.stories.voices import VOICE_STYLES

    patterns = []
    for voice in VOICE_STYLES.values():
        patterns.append(re.compile(rf"\b{re.escape(voice.name)}\b"))
        title = voice.name.split()[-1]
        patterns.append(re.compile(rf"\b(?:[Tt]he|[Aa]) {re.escape(title)}\b"))
    return tuple(patterns)


def check_faithfulness(text: str, source_texts: Iterable[str]) -> list[str]:
    """Flag numbers and proper nouns that the cited facts do not contain.

    Limits, stated honestly: numbers are only recognised when written as digits
    ("three" is not checked); a capitalised word that starts a sentence is not
    treated as a proper noun, so a name at the very start of a sentence is missed;
    and a name is matched word by word, not as a phrase. Proverb text is excluded
    because it comes from the verified corpus, not from the writer.
    """
    sources = list(source_texts)
    source_numbers = {_normalise_number(n) for s in sources for n in NUMBER_PATTERN.findall(s)}
    source_words = {_strip_possessive(w) for s in sources for w in WORD_PATTERN.findall(s)}

    writer_text = SLOT_PATTERN.sub(" . ", text)
    problems = []
    for number in NUMBER_PATTERN.findall(writer_text):
        if _normalise_number(number) not in source_numbers:
            problems.append(f"mentions the number {number}, which is not in the facts.")
    for name in proper_nouns(writer_text):
        if name not in source_words:
            problems.append(f"mentions {name!r}, which is not in the facts or event title.")
    return _unique(problems)


def proper_nouns(text: str) -> list[str]:
    """Return capitalised words that do not start a sentence."""
    names = []
    for match in WORD_PATTERN.finditer(text):
        word = match.group(0)
        if not word[0].isupper() or word == "I":
            continue
        before = text[: match.start()].rstrip(" \t\"'‘’([")
        if not before or before[-1] in SENTENCE_END:
            continue
        names.append(_strip_possessive(word))
    return names


def check_copy(text: str, evidence_notes: Iterable[str]) -> list[str]:
    """Reject 15 or more consecutive words shared with any evidence note."""
    writer_words = _lower_words(SLOT_PATTERN.sub(" ", text))
    windows = _ngrams(writer_words, COPY_GUARD_WORDS)
    for note in evidence_notes:
        if windows & _ngrams(_lower_words(note), COPY_GUARD_WORDS):
            return [
                f"shares {COPY_GUARD_WORDS}+ consecutive words with an evidence note; "
                "retell in your own words."
            ]
    return []


def check_closing(
    closing_kind: str, closing_text: str, source_texts: Iterable[str], tone_class: str
) -> list[str]:
    """Check the moral/reflection shape and the parts of its safety code can see.

    Code cannot judge whether a closing infers motives or takes a side; it does stop
    a closing from naming anyone or anything the facts do not, and on a sensitive
    story it stops a closing from naming anyone at all.
    """
    text = closing_text.strip()
    if closing_kind == "none":
        return ["closing_text must be empty when closing_kind is none."] if text else []
    problems = []
    if not text:
        problems.append(f"closing_text is required when closing_kind is {closing_kind}.")
    if len(text) > MAX_CLOSING_CHARS:
        problems.append(f"closing_text has {len(text)} characters; limit is {MAX_CLOSING_CHARS}.")
    if find_slots(text) or "{{" in text:
        problems.append("closing_text may not contain proverb slots.")
    if any(mark in text for mark in QUOTATION_MARKS) or SINGLE_QUOTED.search(text):
        problems.append("closing_text contains a quotation mark.")
    if ATTRIBUTION_PATTERN.search(text):
        # The closing holds no proverb, so any credit to tradition would be invented.
        problems.append(
            "closing_text credits tradition (for example 'as the elders say'); "
            "the closing is Greeo's own words and may not."
        )
    problems.extend(f"closing_text {p}" for p in check_storyteller_names(text))
    if tone_class == "sensitive":
        if closing_kind == "moral":
            problems.append("sensitive stories use a reflection or no closing, not a moral.")
        if proper_nouns(text):
            problems.append("a closing on a sensitive story may not name anyone or anywhere.")
    problems.extend(f"closing_text {p}" for p in check_faithfulness(text, source_texts))
    return problems


def check_tone_rules(tone_class: str, tones: Iterable[str], has_proverbs: bool) -> list[str]:
    """Sensitive events get no light telling and no proverbs."""
    if tone_class != "sensitive":
        return []
    problems = []
    if "light" in tones:
        problems.append("sensitive stories may not have a light telling.")
    if has_proverbs:
        problems.append("sensitive stories may not use proverbs.")
    return problems


def check_citations(evidence_keys: list[str], known_keys: set[str]) -> list[str]:
    """Every fact, context item and perspective must cite existing evidence."""
    if not evidence_keys:
        return ["must cite at least one evidence key."]
    return [
        f"cites unknown evidence key {key!r}." for key in evidence_keys if key not in known_keys
    ]


def perspective_publishers(
    perspective_evidence: Iterable[list[str]], publisher_by_key: Mapping[str, str]
) -> set[str]:
    """Distinct publishers behind all perspectives; fewer than two means no perspectives."""
    return {
        publisher_by_key[key]
        for keys in perspective_evidence
        for key in keys
        if key in publisher_by_key
    }


def check_voice_vocabulary(text: str) -> list[str]:
    """Words Alexa+ forbids in customer speech; caught here, not when a listener asks."""
    found = forbidden_words(SLOT_PATTERN.sub(" ", text))
    return [f"contains {word!r}, which Greeo never says aloud; rephrase it." for word in found]


def check_banned_phrases(text: str, phrases: Iterable[str]) -> list[str]:
    """Case-insensitive search for owner-maintained banned phrases."""
    lowered = text.casefold()
    return [f"contains banned phrase {p!r}." for p in phrases if p.casefold() in lowered]


@lru_cache
def banned_phrases() -> tuple[str, ...]:
    """Load data/banned_phrases.txt; blank lines and # comments are ignored."""
    path = Path(settings.BASE_DIR).parent / "data" / "banned_phrases.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    return tuple(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def _normalise_number(value: str) -> str:
    return value.replace(",", "").rstrip(".")


def _strip_possessive(word: str) -> str:
    for suffix in ("'s", "’s"):
        if word.endswith(suffix):
            return word[: -len(suffix)]
    return word.rstrip("'’-")


def _lower_words(text: str) -> list[str]:
    return [w.casefold() for w in WORD_PATTERN.findall(text)]


def _ngrams(words: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))
