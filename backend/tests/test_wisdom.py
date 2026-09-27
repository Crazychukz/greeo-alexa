from __future__ import annotations

import json
from io import StringIO

import pytest
from apps.stories.models import Story
from apps.wisdom.models import Proverb
from apps.wisdom.services import candidates_for_story, pick_proverbs
from django.core.management import call_command
from django.core.management.base import CommandError

from tests.factories import ProverbFactory, StoryFactory


@pytest.mark.django_db
def test_sensitive_stories_receive_no_candidates_and_a_sensitive_reason() -> None:
    story = StoryFactory(tone_class=Story.ToneClass.SENSITIVE)

    assert candidates_for_story(["patience"], story.tone_class) == []
    assert pick_proverbs(story)[0].reason_code == "sensitive_story"


@pytest.mark.django_db
def test_only_verified_tone_approved_proverbs_are_candidates() -> None:
    good = ProverbFactory(themes=["patience"])
    ProverbFactory(verification_status=Proverb.VerificationStatus.UNVERIFIED, themes=["patience"])
    ProverbFactory(
        verification_status=Proverb.VerificationStatus.SINGLE_SOURCE, themes=["patience"]
    )
    ProverbFactory(verification_status=Proverb.VerificationStatus.DISPUTED, themes=["patience"])
    ProverbFactory(tone_ok=False, themes=["patience"])

    assert candidates_for_story(["patience"], Story.ToneClass.NEUTRAL) == [good]


@pytest.mark.django_db
def test_import_rejects_bad_row_without_partial_writes(tmp_path) -> None:
    corpus = tmp_path / "proverbs.jsonl"
    valid = {
        "original_text": "TEST PROVERB IMPORT GOOD",
        "language": "Test language",
        "spoken_form": "Test spoken form",
        "translation": "Test translation",
        "meaning_note": "Test meaning",
        "speak_original_ok": False,
        "culture": "Test culture",
        "region": "Test region",
        "source_citation": "Test source one",
        "second_source_citation": "Test source two",
        "license": "Test license",
        "verification_status": "verified",
        "dispute_note": "",
        "themes": ["patience"],
        "tone_ok": True,
    }
    invalid = valid | {"original_text": "TEST PROVERB IMPORT BAD", "culture": "African"}
    corpus.write_text("\n".join([json.dumps(valid), json.dumps(invalid)]), encoding="utf-8")

    with pytest.raises(CommandError, match="culture must be specific"):
        call_command("import_proverbs", corpus)

    assert Proverb.objects.count() == 0


@pytest.mark.django_db
def test_import_rejects_unknown_themes_and_missing_verified_spoken_form(tmp_path) -> None:
    corpus = tmp_path / "proverbs.jsonl"
    entry = {
        "original_text": "TEST PROVERB INVALID",
        "language": "Test language",
        "spoken_form": "",
        "translation": "",
        "meaning_note": "Test meaning",
        "speak_original_ok": False,
        "culture": "Test culture",
        "region": "Test region",
        "source_citation": "Test source one",
        "second_source_citation": "Test source two",
        "license": "Test license",
        "verification_status": "verified",
        "dispute_note": "",
        "themes": ["not_a_theme"],
        "tone_ok": True,
    }
    corpus.write_text(json.dumps(entry), encoding="utf-8")

    with pytest.raises(CommandError, match="Unknown theme"):
        call_command("import_proverbs", corpus)
    assert Proverb.objects.count() == 0


@pytest.mark.django_db
def test_proverb_audit_reports_synthetic_fixture_coverage() -> None:
    ProverbFactory(themes=["patience"])
    output = StringIO()

    call_command("proverb_audit", stdout=output)

    assert "verified: 1" in output.getvalue()
    assert "Themes with zero servable proverbs:" in output.getvalue()
