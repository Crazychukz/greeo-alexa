"""A whole tale becomes spoken beats in code; the checks that guard it."""

from __future__ import annotations

from apps.stories import validators
from apps.stories.composition import (
    TellingDraft,
    split_tale,
    spoken_words,
    used_slots,
)
from apps.wisdom.rendering import fill_slots

OFFERED = {"P1": "When the drumbeat changes, the dance must change.", "P2": "TEST PROVERB TWO."}


def sentence(n: int, words: int = 12) -> str:
    return " ".join(["word"] * (words - 1) + [f"end{n}."])


def test_a_long_tale_is_split_into_balanced_beats_at_sentence_ends() -> None:
    tale = " ".join(sentence(n) for n in range(20))  # 240 words

    beats, problems = split_tale(tale, {})

    assert problems == []
    assert 3 <= len(beats) <= 5
    sizes = [spoken_words(beat, {}) for beat in beats]
    assert max(sizes) <= 75 and max(sizes) - min(sizes) <= 24
    assert " ".join(beats) == tale
    assert all(beat.endswith(".") for beat in beats)


def test_slots_count_as_their_proverbs_words_when_splitting() -> None:
    tale = "Sit and listen. She knew that {{P1}} " + " ".join(sentence(n, 20) for n in range(4))

    beats, problems = split_tale(tale, OFFERED)

    assert problems == []
    assert spoken_words(beats[0], OFFERED) >= 10


def test_a_sentence_over_the_beat_limit_is_reported_not_cut() -> None:
    tale = f"{sentence(1, 80)} {sentence(2)} {sentence(3)}"

    _, problems = split_tale(tale, {})

    assert any("over the 75-word beat limit" in p for p in problems)


def test_only_slots_in_the_tale_are_used_and_misuse_is_reported() -> None:
    draft = TellingDraft(
        tale="As the Akan say, {{P1}} And again {{P1}} and {{P9}}.",
        proverbs_used=["P1", "P2"],
        closing_kind="none",
    )

    spoken, problems = used_slots(draft, OFFERED)

    assert spoken == {"P1": OFFERED["P1"]}
    assert any("P1}} 2 times" in p for p in problems)
    assert any("P9}}, which was not offered" in p for p in problems)
    assert any("P2 is listed as used" in p for p in problems)


def test_woven_proverbs_read_naturally_without_changing_their_words() -> None:
    assert (
        fill_slots("Lily knew that {{P1}} And so she did.", OFFERED)
        == "Lily knew that when the drumbeat changes, the dance must change. And so she did."
    )
    assert fill_slots("As the Akan say, {{P1}}", OFFERED).endswith(
        ", when the drumbeat changes, the dance must change."
    )
    assert fill_slots("It came true: {{P1}}", OFFERED).endswith(
        ": When the drumbeat changes, the dance must change."
    )
    assert (
        fill_slots("The saying of {{P1}}", {"P1": "Ogun is at home."})
        == "The saying of Ogun is at home."
    )


def test_fill_slots_merges_punctuation() -> None:
    assert fill_slots("Listen. {{P1}}.", {"P1": "A proverb."}) == "Listen. A proverb."
    assert fill_slots("Listen. {{P1}}", {"P1": "A proverb"}) == "Listen. A proverb."
    assert fill_slots("Is it {{P1}}?", {"P1": "so"}) == "Is it so?"
    planted = fill_slots("{{P1}}, for we must.", {"P1": "Plant a tree."})
    assert planted == "Plant a tree, for we must."


def test_writing_out_a_proverbs_words_instead_of_its_slot_is_caught() -> None:
    copied = "She knew that when the drumbeat changes, the dance must change."

    assert validators.check_proverb_copies(copied, OFFERED)
    assert validators.check_proverb_copies("She knew that {{P1}} The dance went on.", OFFERED) == []


def test_quoted_speech_in_single_quotes_is_caught_but_apostrophes_are_not() -> None:
    quoted = ["He declared, 'It is time for us to steer our own ship.' And so.", "b.", "c."]
    fine = ["Dangote's refinery opened on the Africans' land.", "It's done.", "c."]

    assert any("quotation mark" in p for p in validators.check_beats(quoted, {}))
    assert validators.check_beats(fine, {}) == []


def test_a_closing_may_not_credit_tradition() -> None:
    problems = validators.check_closing(
        "reflection", "As the elders say, every step forward has its challenges.", [], "neutral"
    )

    assert any("credits tradition" in p for p in problems)


def test_the_storyteller_is_never_named_in_a_tale() -> None:
    named = [
        "Moonlight Elder, calm and slow, tells us of his words.",
        "As the Wise Judge speaks, he tells us.",
        "From challenges, growth springs forth, as the Trickster would jest.",
    ]

    for text in named:
        assert validators.check_storyteller_names(text), text
    assert validators.check_storyteller_names("A wise judge would weigh both sides.") == []
