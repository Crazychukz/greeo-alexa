"""The friction log, retold: each entry in docs/FRICTION_LOG.md becomes a demo story.

Each entry goes through the same editorial pipeline as the news, with the entry itself
as the evidence: facts are established from it, proverbs chosen by meaning, the tale
written, checked by the rules and the editor model, and published. The stories are
marked as demo stories, so they are told on request and never listed as today's news.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction

from apps.core.models import PipelineRun
from apps.llm.client import LLMGateway
from apps.news.article import ArticleText
from apps.news.models import Article, SourceFeed

from .models import Story
from .pipeline import StoryRejected, build_story, cluster_key

LOG_PATH = Path(settings.BASE_DIR).parent / "docs" / "FRICTION_LOG.md"
LOG_URL = "https://github.com/Crazychukz/greeo-alexa/blob/main/docs/FRICTION_LOG.md"
PUBLISHER = "Greeo friction log"
REGION = "Behind the scenes"
# Friction is not a tragedy: a light telling (the Playful Trickster) and a balanced one.
TONES = ("light", "balanced")

LINK = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")
FIELD = re.compile(r"^- \*\*(.+?):\*\*\s*(.*)$")
HEADING = re.compile(r"^(\d{4}-\d{2}-\d{2}):\s*(.+)$")


@dataclass(frozen=True)
class FrictionEntry:
    date: str
    title: str
    fields: dict[str, str]  # label -> plain text, links reduced to their words

    @property
    def link(self) -> str:
        """The doc the entry is about, when it links one; otherwise the log itself."""
        return self.fields.get("_link", "") or LOG_URL

    @property
    def spoken_date(self) -> str:
        """7 October 2026: a tale says the date aloud, so never 2026-10-07."""
        day = datetime.fromisoformat(self.date)
        return f"{day.day} {day:%B %Y}"

    @property
    def severity(self) -> str:
        found = re.search(r"critical|high|medium|low", self.fields.get("Severity", ""), re.I)
        return found.group(0).capitalize() if found else "Unrated"

    def as_evidence(self) -> str:
        """The entry as the text the facts are established from."""
        lines = [f"Friction log entry, {self.spoken_date}: {self.title}."]
        lines += [f"{label}: {text}" for label, text in self.fields.items() if label != "_link"]
        return "\n".join(lines)


def parse_log(markdown: str) -> list[FrictionEntry]:
    """Entries after "## Entries", in the order written; the template is skipped."""
    body = re.split(r"^## Entries\s*$", markdown, flags=re.M)
    if len(body) < 2:
        return []
    entries = []
    for block in re.split(r"^### ", body[1], flags=re.M)[1:]:
        heading, *lines = block.strip().splitlines()
        match = HEADING.match(heading.strip())
        if not match:
            continue
        fields: dict[str, str] = {}
        label = None
        for line in lines:
            field = FIELD.match(line)
            if field:
                label = field.group(1)
                fields[label] = field.group(2)
            elif label and line.strip():
                fields[label] += " " + line.strip()
        links = [url for text in fields.values() for _, url in LINK.findall(text)]
        plain = {k: re.sub(r"\*\*|`", "", LINK.sub(r"\1", v)).strip() for k, v in fields.items()}
        if links:
            plain["_link"] = links[0]
        entries.append(FrictionEntry(match.group(1), match.group(2).strip(), plain))
    return entries


def tell_friction_log(
    *, replace: bool = False, gateway: Any | None = None, path: Path = LOG_PATH
) -> dict[str, str]:
    """Make a demo story of every entry not yet told. Returns entry title -> outcome."""
    entries = parse_log(path.read_text(encoding="utf-8"))
    run = PipelineRun.objects.create()
    gateway = gateway or LLMGateway()
    outcome: dict[str, str] = {}
    for entry in entries:
        article = _evidence(entry)
        existing = Story.objects.filter(cluster_key=cluster_key(article)).first()
        if existing and not replace:
            outcome[entry.title] = f"already told as {existing.pk}"
            continue
        try:
            with transaction.atomic():
                if existing:
                    existing.delete()
                story = build_story(
                    article,
                    run,
                    gateway,
                    lambda url, entry=entry: _read(entry, url),
                    tones=TONES,
                    extra_facts=(
                        f"Greeo's friction log records this problem on {entry.spoken_date} "
                        f"and rates it {entry.severity.lower()} severity.",
                    ),
                )
                story.is_demo = True
                story.save(update_fields=["is_demo"])
        except StoryRejected as rejected:
            outcome[entry.title] = "not published: " + "; ".join(rejected.reasons)
            continue
        outcome[entry.title] = f"published {story.pk}: {story.handle}"
    run.status = PipelineRun.Status.OK
    run.finished_at = datetime.now(UTC)
    run.save(update_fields=["status", "finished_at"])
    return outcome


def _read(entry: FrictionEntry, url: str) -> ArticleText:
    text = entry.as_evidence()
    return ArticleText(url=url, text=text, words=len(text.split()))


def _evidence(entry: FrictionEntry) -> Article:
    """The entry as an Article from an inactive, never-fetched friction-log source."""
    feed_url = "curated://greeo-friction-log"
    source, _ = SourceFeed.objects.get_or_create(
        feed_url=feed_url,
        defaults={
            "name": PUBLISHER,
            "region": REGION,
            "language": "en",
            "terms_url": LOG_URL,
            "attribution_text": PUBLISHER,
            "active": False,
            "use_policy": SourceFeed.UsePolicy.BLOCKED,
        },
    )
    # One article per entry, even when two entries link the same doc page.
    identity = f"friction:{entry.date}:{entry.title}"
    article, _ = Article.objects.update_or_create(
        url_hash=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        defaults={
            "source": source,
            "evidence_kind": Article.EvidenceKind.CURATED,
            "url_clean": entry.link,
            "title": entry.title,
            "snippet": f"Friction log, {entry.date}: {entry.title}"[:300],
            "published_at": datetime.fromisoformat(entry.date).replace(tzinfo=UTC),
            "language": "en",
            "region_tags": [REGION],
        },
    )
    return article
