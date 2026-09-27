"""Curated event loading: every content rule, on synthetic data only."""

from __future__ import annotations

import copy
from io import StringIO
from pathlib import Path

import pytest
import yaml
from apps.core.models import StageTrace
from apps.news.models import Article, SourceFeed
from apps.stories import validators
from apps.stories.curated import (
    CuratedEvent,
    CuratedEventError,
    load_curated_event,
    parse_curated_event,
)
from apps.stories.models import Story, StoryTelling
from apps.wisdom.models import Proverb
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from tests.factories import ProverbFactory

DATA_DIR = Path(settings.BASE_DIR).parent / "data"
FIXTURE = DATA_DIR / "demo_event.synthetic.yaml"


@pytest.fixture(autouse=True)
def synthetic_proverbs(db) -> None:
    ProverbFactory(id="pv_synthetic01", spoken_form="Test proverb one is spoken here.")
    ProverbFactory(id="pv_synthetic02", spoken_form="Test proverb two is spoken here.")


def fixture_data() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def load(data: dict, *, synthetic: bool = True, replace: bool = False):
    return load_curated_event(
        CuratedEvent.model_validate(data), synthetic=synthetic, replace=replace
    )


def errors_for(data: dict, *, synthetic: bool = True) -> str:
    with pytest.raises(CuratedEventError) as caught:
        load(data, synthetic=synthetic)
    return "\n".join(caught.value.report.errors)


def balanced_beats(data: dict) -> list[str]:
    return data["tellings"]["balanced"]["beats"]


def test_template_refuses_to_load() -> None:
    text = (DATA_DIR / "demo_event.template.yaml").read_text(encoding="utf-8")

    with pytest.raises(CuratedEventError, match="TODO"):
        parse_curated_event(text)


def test_synthetic_event_loads_every_layer_and_publishes() -> None:
    result = load(fixture_data())

    story = result.story
    assert story.status == Story.Status.PUBLISHED
    assert story.is_synthetic is True
    assert story.facts.count() == 3
    assert story.context_items.count() == 1
    assert story.perspectives.count() == 2
    assert sorted(story.tellings.values_list("tone", flat=True)) == ["balanced", "serious"]
    balanced = story.tellings.get(tone=StoryTelling.Tone.BALANCED)
    assert balanced.is_curated and balanced.status == StoryTelling.Status.PUBLISHED
    assert balanced.beats.count() == 3
    assert set(balanced.proverb_links.values_list("slot", flat=True)) == {"P1", "P2"}
    assert all(fact.articles.exists() for fact in story.facts.all())
    assert StageTrace.objects.get(stage="curated_load").status == StageTrace.Status.OK


def test_evidence_is_stored_as_curated_metadata_with_clean_urls() -> None:
    load(fixture_data())

    article = Article.objects.get(title="SYNTHETIC: Veloria footbridge opens")
    assert article.evidence_kind == Article.EvidenceKind.CURATED
    assert "utm_source" not in article.url_clean
    assert article.snippet.startswith("SYNTHETIC NOTE")
    feed = article.source
    assert feed.feed_url == "curated://synthetic-gazette"
    assert feed.active is False and feed.use_policy == SourceFeed.UsePolicy.BLOCKED


def test_synthetic_story_is_hidden_unless_allowed() -> None:
    story = load(fixture_data()).story

    with override_settings(ALLOW_SYNTHETIC=False):
        assert story not in Story.objects.listable()
    with override_settings(ALLOW_SYNTHETIC=True):
        assert story in Story.objects.listable()


def test_synthetic_flag_must_match_the_title() -> None:
    assert "must be loaded with --synthetic" in errors_for(fixture_data(), synthetic=False)

    data = fixture_data()
    data["event"]["title"] = "A real looking title"
    assert "--synthetic requires" in errors_for(data, synthetic=True)


def test_invalid_citation_is_reported() -> None:
    data = fixture_data()
    data["facts"][0]["evidence"] = ["missing-key"]

    assert "facts[1]: cites unknown evidence key 'missing-key'" in errors_for(data)


def test_single_publisher_perspectives_are_not_stored() -> None:
    data = fixture_data()
    for perspective in data["perspectives"]:
        perspective["evidence"] = ["gazette-opening"]

    result = load(data)

    assert result.story.perspectives.count() == 0
    assert any("fewer than two publishers" in warning for warning in result.warnings)


def test_beat_with_quotation_mark_is_rejected() -> None:
    data = fixture_data()
    balanced_beats(data)[1] = 'So 300 households said "we will build it".'

    assert "beat 2 contains a quotation mark" in errors_for(data)


def test_beat_with_unknown_slot_is_rejected() -> None:
    data = fixture_data()
    balanced_beats(data)[1] += " The elders say {{P9}}"

    assert "beat 2 uses unknown slot {{P9}}" in errors_for(data)


def test_each_mapped_slot_must_be_used_exactly_once() -> None:
    data = fixture_data()
    balanced_beats(data)[1] += " An old proverb says {{P1}}"

    assert "slot {{P1}} must be used exactly once, found 2" in errors_for(data)


def test_beat_over_75_words_after_rendering_is_rejected() -> None:
    Proverb.objects.filter(pk="pv_synthetic01").update(spoken_form="word " * 60)

    assert "beat 1 has" in errors_for(fixture_data())
    assert "words after proverb substitution" in errors_for(fixture_data())


def test_number_absent_from_facts_is_rejected() -> None:
    data = fixture_data()
    balanced_beats(data)[1] = "So 450 households gathered what they had, until the bridge stood."

    assert "mentions the number 450" in errors_for(data)


def test_proper_noun_absent_from_facts_is_rejected() -> None:
    data = fixture_data()
    balanced_beats(data)[1] = "So the households of Marrowdale gathered what they had."

    assert "mentions 'Marrowdale'" in errors_for(data)


def test_unverified_proverb_is_rejected() -> None:
    Proverb.objects.filter(pk="pv_synthetic02").update(
        verification_status=Proverb.VerificationStatus.SINGLE_SOURCE
    )

    assert "pv_synthetic02 is single_source" in errors_for(fixture_data())


def test_light_tone_and_proverbs_are_rejected_on_sensitive_events() -> None:
    data = fixture_data()
    data["event"]["tone_class"] = "sensitive"
    data["tellings"]["light"] = copy.deepcopy(data["tellings"]["balanced"])

    errors = errors_for(data)

    assert "sensitive stories may not have a light telling" in errors
    assert "sensitive stories may not use proverbs" in errors


def test_copy_guard_rejects_fifteen_shared_words() -> None:
    data = fixture_data()
    balanced_beats(data)[1] = (
        "Describes children using canoes to reach school before the bridge and yearly "
        "floods at the old crossing."
    )

    assert "shares 15+ consecutive words with an evidence note" in errors_for(data)


def test_attribution_phrase_must_introduce_a_proverb_slot() -> None:
    data = fixture_data()
    balanced_beats(data)[1] = "The elders say that the river always wins. So they built it."

    assert "without a proverb slot straight after it" in errors_for(data)


def test_closing_rules() -> None:
    data = fixture_data()
    data["tellings"]["balanced"]["closing_kind"] = "none"
    assert "closing_text must be empty" in errors_for(data)

    data = fixture_data()
    data["tellings"]["balanced"]["closing_text"] = "Veloria teaches that " + "x" * 200
    assert "limit is 200" in errors_for(data)

    data = fixture_data()
    data["event"]["tone_class"] = "sensitive"
    data["tellings"]["balanced"]["closing_kind"] = "moral"
    data["tellings"]["balanced"]["closing_text"] = "The people of Veloria chose well."
    errors = errors_for(data)
    assert "not a moral" in errors
    assert "may not name anyone or anywhere" in errors


def test_banned_phrases_are_rejected(monkeypatch) -> None:
    monkeypatch.setattr(validators, "banned_phrases", lambda: ("stone and rope",))

    assert "contains banned phrase 'stone and rope'" in errors_for(fixture_data())


def test_unknown_yaml_keys_are_reported() -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace("region: Veloria", "regoin: Veloria", 1)

    with pytest.raises(CuratedEventError) as caught:
        parse_curated_event(text)

    errors = "\n".join(caught.value.report.errors)
    assert "event.regoin: Extra inputs are not permitted" in errors


def test_failed_load_writes_nothing(monkeypatch) -> None:
    def refuse(self: Story) -> None:
        raise ValidationError("synthetic publication failure")

    monkeypatch.setattr(Story, "publish", refuse)

    with pytest.raises(CuratedEventError, match="synthetic publication failure"):
        load(fixture_data())

    assert Story.objects.count() == 0
    assert Article.objects.count() == 0
    assert SourceFeed.objects.count() == 0
    assert StageTrace.objects.get(stage="curated_load").status == StageTrace.Status.FAILED


def test_reload_requires_replace_and_keeps_the_story_id() -> None:
    first = load(fixture_data()).story

    assert "use --replace" in errors_for(fixture_data())

    data = fixture_data()
    data["tellings"]["balanced"]["closing_text"] = "Some bridges are built by patience."
    second = load(data, replace=True).story

    assert second.pk == first.pk
    assert Story.objects.count() == 1
    assert second.tellings.get(tone="balanced").moral == "Some bridges are built by patience."


def test_command_reports_every_problem_at_once(tmp_path) -> None:
    bad = fixture_data()
    balanced_beats(bad)[1] = 'So 450 households said "yes".'
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")

    with pytest.raises(CommandError) as caught:
        call_command("load_demo_event", path, synthetic=True)

    message = str(caught.value)
    assert "nothing was written" in message
    assert "contains a quotation mark" in message
    assert "mentions the number 450" in message
    assert Story.objects.count() == 0


def test_seed_command_loads_the_synthetic_fixture() -> None:
    output = StringIO()
    call_command("seed_synthetic", stdout=output)

    assert "Loaded st_" in output.getvalue()
    assert Story.objects.get().is_synthetic is True


@override_settings(ALLOW_SYNTHETIC=False)
def test_seed_refuses_when_synthetic_data_is_disabled() -> None:
    with pytest.raises(CommandError, match="ALLOW_SYNTHETIC is off"):
        call_command("seed_synthetic")


def test_single_source_proverb_loads_only_in_demo_mode() -> None:
    Proverb.objects.filter(pk="pv_synthetic02").update(
        verification_status=Proverb.VerificationStatus.SINGLE_SOURCE,
        second_source_citation="",
    )

    with override_settings(DEMO_ALLOW_SINGLE_SOURCE_PROVERBS=False):
        assert "pv_synthetic02 is single_source" in errors_for(fixture_data())
    with override_settings(DEMO_ALLOW_SINGLE_SOURCE_PROVERBS=True):
        assert load(fixture_data()).story.status == Story.Status.PUBLISHED
