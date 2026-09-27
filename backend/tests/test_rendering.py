"""Proverb slots become exact verified text, and nothing else ever does."""

from __future__ import annotations

import pytest
from apps.wisdom.models import Proverb
from apps.wisdom.rendering import RenderingError, fill_slots, find_slots, render_beat

from tests.factories import ProverbFactory, TellingBeatFactory, TellingProverbFactory


def test_fill_slots_substitutes_exact_text_and_refuses_unknown_slots() -> None:
    assert fill_slots("Listen. {{P1}} Then rest.", {"P1": "TEST PROVERB 1."}) == (
        "Listen. TEST PROVERB 1. Then rest."
    )
    assert find_slots("{{P1}} and {{P2}} and {{P1}}") == ["P1", "P2", "P1"]

    with pytest.raises(RenderingError, match="P2"):
        fill_slots("{{P2}}", {"P1": "TEST PROVERB 1."})


@pytest.mark.django_db
def test_render_beat_exposes_culture_and_original_text_for_cards() -> None:
    link = TellingProverbFactory(
        slot="P1",
        proverb=ProverbFactory(
            original_text="TEST ORIGINAL 1",
            spoken_form="TEST PROVERB 1.",
            culture="Test culture",
        ),
    )
    beat = TellingBeatFactory(telling=link.telling, text_template="The elders say {{P1}}")

    rendered = render_beat(beat)

    assert rendered.text == "The elders say TEST PROVERB 1."
    assert rendered.proverbs[0].original_text == "TEST ORIGINAL 1"
    assert rendered.proverbs[0].culture == "Test culture"
    assert rendered.proverbs[0].source_citation == "Synthetic source one"
    assert rendered.proverbs[0].verification_status == "verified"


@pytest.mark.django_db
def test_render_beat_refuses_a_proverb_disputed_after_publication() -> None:
    link = TellingProverbFactory(slot="P1")
    beat = TellingBeatFactory(telling=link.telling, text_template="{{P1}}")
    Proverb.objects.filter(pk=link.proverb_id).update(
        verification_status=Proverb.VerificationStatus.DISPUTED
    )

    with pytest.raises(RenderingError, match="not servable"):
        render_beat(beat)


@pytest.mark.django_db
def test_render_beat_refuses_an_unmapped_slot() -> None:
    beat = TellingBeatFactory(text_template="{{P3}}")

    with pytest.raises(RenderingError, match="unmapped slot"):
        render_beat(beat)
