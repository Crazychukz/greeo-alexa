"""Storyteller voices: which voice may tell which tone of which story, and tale shape."""

from __future__ import annotations

import pytest
import yaml
from apps.llm.prompt_registry import load_prompt
from apps.stories.curated import CuratedEvent, CuratedEventError, load_curated_event
from apps.stories.models import Story, StoryTelling
from apps.stories.voices import (
    ROLE_GUIDANCE,
    VOICE_STYLES,
    beat_roles,
    voice_for,
    voice_problems,
)
from django.core.exceptions import ValidationError

from tests.factories import ProverbFactory, StoryFactory, StoryTellingFactory
from tests.test_curated_event import FIXTURE

TONES = ("light", "balanced", "serious")


def test_every_tone_has_a_default_voice_that_is_allowed_to_tell_it() -> None:
    for tone in TONES:
        voice = voice_for(tone, "neutral")
        assert voice_problems(voice.key, tone, "neutral") == []
    for tone in ("balanced", "serious"):
        voice = voice_for(tone, "sensitive")
        assert voice.sensitive_ok and voice_problems(voice.key, tone, "sensitive") == []


def test_playful_and_judging_voices_are_kept_off_sensitive_stories() -> None:
    assert (
        "not used on sensitive stories"
        in voice_problems("playful_trickster", "light", "sensitive")[0]
    )
    assert voice_problems("wise_judge", "serious", "sensitive")
    assert voice_for("serious", "sensitive", requested="wise_judge").key == "hopeful_healer"


def test_a_voice_only_tells_its_own_tones() -> None:
    assert "not used for a light telling" in voice_problems("wise_judge", "light", "neutral")[0]
    assert voice_problems("village_fire", "balanced", "neutral") == []
    assert voice_for("balanced", "neutral", requested="village_fire").key == "village_fire"
    assert "unknown voice" in voice_problems("town_crier", "balanced", "neutral")[0]


def test_voice_styles_never_ask_for_dialect_or_judgement() -> None:
    for voice in VOICE_STYLES.values():
        lowered = voice.style.lower()
        assert "accent" not in lowered and "dialect" not in lowered
        assert 80 <= voice.rate_percent <= 105
    assert "never rules on who is right" in VOICE_STYLES["wise_judge"].style


def test_beat_roles_cover_three_to_five_beats_and_end_in_resolution() -> None:
    for count in (3, 4, 5):
        roles = beat_roles(count)
        assert len(roles) == count
        assert roles[0] == "opening" and roles[-1] == "resolution"
        assert all(role in ROLE_GUIDANCE for role in roles)
    assert "No invented ending" in ROLE_GUIDANCE["resolution"]


@pytest.mark.django_db
def test_telling_validation_rejects_a_voice_that_does_not_fit() -> None:
    sensitive = StoryFactory(tone_class=Story.ToneClass.SENSITIVE)
    telling = StoryTellingFactory.build(
        story=sensitive, tone=StoryTelling.Tone.SERIOUS, voice_style="wise_judge"
    )

    with pytest.raises(ValidationError, match="not used on sensitive stories"):
        telling.clean()

    telling.voice_style = ""
    telling.clean()
    assert telling.voice.key == "hopeful_healer"


@pytest.mark.django_db
def test_curated_event_can_choose_a_voice_and_bad_choices_are_reported() -> None:
    ProverbFactory(id="pv_synthetic01", spoken_form="Test proverb one is spoken here.")
    ProverbFactory(id="pv_synthetic02", spoken_form="Test proverb two is spoken here.")
    data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))

    story = load_curated_event(CuratedEvent.model_validate(data), synthetic=True).story

    assert story.tellings.get(tone="serious").voice.key == "hopeful_healer"
    assert story.tellings.get(tone="balanced").voice.key == "moonlight_elder"

    data["tellings"]["serious"]["voice"] = "playful_trickster"
    with pytest.raises(CuratedEventError) as caught:
        load_curated_event(CuratedEvent.model_validate(data), synthetic=True, replace=True)
    assert "tellings.serious.voice: the Playful Trickster voice is not used for a serious" in (
        "\n".join(caught.value.report.errors)
    )


def test_writer_prompt_carries_the_storytelling_craft_and_hard_rules() -> None:
    prompt = load_prompt("write_telling")

    assert prompt.version == "v4"
    for phrase in (
        "`voice`",
        "turning point",
        "exaggeration",
        "never changes them, never adds a number",
        "{{P1}}",
        "never its words",
        "Never\n  name or describe yourself",
        "never invent an ending",
        "quotation marks",
        "No dialect",
        "If `tone_class` is sensitive",
    ):
        assert phrase in prompt.text, phrase
