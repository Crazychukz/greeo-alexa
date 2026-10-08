"""The friction log, retold as demo stories."""

from __future__ import annotations

from pathlib import Path

import pytest
from apps.mcp_server import handlers
from apps.stories.friction import parse_log, tell_friction_log
from apps.stories.models import Story

from tests.test_pipeline import ScriptedGateway

pytestmark = pytest.mark.django_db

LOG = """# Friction log

## Entry template

### YYYY-MM-DD: Short title

- **Severity:** Critical | High | Medium | Low

## Entries

### 2026-10-07: SYNTHETIC voices missing in one region

- **Tool / doc:** SYNTHETIC speech service,
  [Voices](https://example.com/voices)
- **Actual result:** SYNTHETIC: `ValidationException` in **one** region.
- **Severity:** Medium

### 2026-09-28: SYNTHETIC protocol versions disagree

- **Tool / doc:** SYNTHETIC toolkit docs
- **Severity:** High for voice products; Medium otherwise.
"""


@pytest.fixture
def log(tmp_path: Path) -> Path:
    path = tmp_path / "FRICTION_LOG.md"
    path.write_text(LOG, encoding="utf-8")
    return path


def test_entries_are_read_with_their_fields_and_links() -> None:
    first, second = parse_log(LOG)

    assert (first.date, first.title, first.severity) == (
        "2026-10-07",
        "SYNTHETIC voices missing in one region",
        "Medium",
    )
    assert first.fields["Tool / doc"] == "SYNTHETIC speech service, Voices"
    assert first.fields["Actual result"] == "SYNTHETIC: ValidationException in one region."
    assert first.link == "https://example.com/voices"
    assert second.severity == "High"
    assert first.spoken_date == "7 October 2026"
    assert second.link.endswith("docs/FRICTION_LOG.md")  # no link: the log itself


def test_each_entry_becomes_a_demo_story_told_light_and_balanced(log: Path) -> None:
    gateway = ScriptedGateway()

    outcome = tell_friction_log(gateway=gateway, path=log)

    assert all(text.startswith("published") for text in outcome.values())
    stories = Story.objects.filter(is_demo=True)
    assert stories.count() == 2
    for story in stories:
        assert story.status == Story.Status.PUBLISHED
        assert sorted(story.tellings.values_list("tone", flat=True)) == ["balanced", "light"]
        assert story.facts.last().text.startswith("Greeo's friction log records this problem")
    evidence = next(v for name, v in gateway.calls if name == "establish_facts")["evidence"]
    assert evidence["publisher"] == "Greeo friction log"
    assert "ValidationException" in evidence["text"]


def test_a_told_entry_is_not_told_twice_unless_replaced(log: Path) -> None:
    tell_friction_log(gateway=ScriptedGateway(), path=log)
    first_ids = set(Story.objects.values_list("pk", flat=True))

    again = tell_friction_log(gateway=ScriptedGateway(), path=log)
    assert all(text.startswith("already told") for text in again.values())

    tell_friction_log(gateway=ScriptedGateway(), path=log, replace=True)
    assert Story.objects.count() == 2
    assert set(Story.objects.values_list("pk", flat=True)).isdisjoint(first_ids)


def test_demo_stories_are_not_today_s_news(log: Path) -> None:
    tell_friction_log(gateway=ScriptedGateway(), path=log)

    with pytest.raises(handlers.FriendlyError):
        handlers.get_briefing(None)
    found = handlers.search_events(None, query="friction log")
    assert found.stories
