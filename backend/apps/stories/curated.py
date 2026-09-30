"""Load one hand-curated event, with its tellings, from YAML.

The curated event is the golden fixture for the vertical slice: the project owner
writes the evidence notes and tellings, and this module checks them with the same
validators the editorial pipeline will use, then writes everything in one transaction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Literal

import yaml
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.text import slugify
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.core.models import StageTrace
from apps.news.models import Article, SourceFeed
from apps.news.services import canonical_url, url_digest
from apps.wisdom.models import Proverb
from apps.wisdom.themes import validate_theme_keys

from . import validators
from .models import (
    Story,
    StoryContext,
    StoryFact,
    StoryPerspective,
    StoryTelling,
    TellingBeat,
    TellingProverb,
)
from .voices import voice_problems

TONES = ("light", "balanced", "serious")


class Strict(BaseModel):
    """Reject unknown keys so a typo in the YAML is reported, not silently ignored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventIn(Strict):
    title: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=100)
    occurred_on: date
    tone_class: Literal["neutral", "sensitive"]
    themes: list[str] = Field(min_length=1)


class EvidenceIn(Strict):
    key: str = Field(pattern=r"^[a-z0-9_-]+$")
    publisher: str = Field(min_length=1, max_length=150)
    headline: str = Field(min_length=1, max_length=500)
    url: str = Field(pattern=r"^https?://")
    published_on: date
    note: str = Field(min_length=1, max_length=300)
    language: str = Field(default="en", max_length=16)


class FactIn(Strict):
    text: str = Field(min_length=1)
    evidence: list[str]


class ContextIn(Strict):
    kind: Literal["background", "why_it_matters", "consequence"]
    text: str = Field(min_length=1)
    evidence: list[str]


class PerspectiveIn(Strict):
    label: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1)
    evidence: list[str]


class ProverbSlotIn(Strict):
    id: str
    role: Literal["opening", "turn", "closing"]


class TellingIn(Strict):
    beats: list[str]
    closing_kind: Literal["moral", "reflection", "none"]
    closing_text: str = ""
    voice: str | None = None


class CuratedEvent(Strict):
    event: EventIn
    evidence: list[EvidenceIn] = Field(min_length=1)
    facts: list[FactIn] = Field(min_length=2)
    context: list[ContextIn] = []
    perspectives: list[PerspectiveIn] = []
    proverbs: dict[str, ProverbSlotIn] = {}
    tellings: dict[Literal["light", "balanced", "serious"], TellingIn]


@dataclass
class Report:
    """Every problem found, so the owner can fix a file in one pass."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, where: str, problems: list[str]) -> None:
        self.errors.extend(f"{where}: {problem}" for problem in problems)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class LoadResult:
    story: Story
    warnings: list[str]


class CuratedEventError(Exception):
    """Raised with the full report when a file must not be loaded."""

    def __init__(self, report: Report) -> None:
        super().__init__("\n".join(report.errors))
        self.report = report


def parse_curated_event(text: str) -> CuratedEvent:
    """Parse YAML text, refusing unfinished templates before any other check."""
    report = Report()
    if "TODO" in text:
        report.errors.append("file still contains TODO placeholders; finish it before loading.")
        raise CuratedEventError(report)
    try:
        data = yaml.safe_load(text)
        return CuratedEvent.model_validate(data)
    except yaml.YAMLError as error:
        report.errors.append(f"YAML could not be read: {error}")
    except ValidationError as error:
        for issue in error.errors():
            where = ".".join(str(part) for part in issue["loc"]) or "file"
            report.errors.append(f"{where}: {issue['msg']}")
    raise CuratedEventError(report)


def validate_curated_event(event: CuratedEvent, *, synthetic: bool) -> Report:
    """Run every content rule and return all problems rather than the first."""
    report = Report()
    info = event.event
    _check_synthetic_flag(info.title, synthetic, report)
    try:
        validate_theme_keys(info.themes)
    except ValueError as error:
        report.errors.append(f"event.themes: {error}")

    keys = [item.key for item in event.evidence]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        report.errors.append(f"evidence: duplicate key(s) {', '.join(duplicates)}.")
    known = set(keys)
    for index, fact in enumerate(event.facts, start=1):
        report.extend(f"facts[{index}]", validators.check_citations(fact.evidence, known))
    for index, item in enumerate(event.context, start=1):
        report.extend(f"context[{index}]", validators.check_citations(item.evidence, known))
    for index, item in enumerate(event.perspectives, start=1):
        report.extend(f"perspectives[{index}]", validators.check_citations(item.evidence, known))
    publishers = validators.perspective_publishers(
        (p.evidence for p in event.perspectives),
        {item.key: publisher_key(item.publisher) for item in event.evidence},
    )
    if event.perspectives and len(publishers) < 2:
        report.warnings.append(
            "perspectives cite fewer than two publishers, so none will be stored."
        )

    spoken_by_slot = _check_proverbs(event, report)
    report.extend(
        "tellings",
        validators.check_tone_rules(info.tone_class, event.tellings, bool(event.proverbs)),
    )
    if "balanced" not in event.tellings:
        report.errors.append("tellings: a balanced telling is required.")

    spoken_layers = [
        *(("facts", i, f.text) for i, f in enumerate(event.facts, start=1)),
        *(("context", i, c.text) for i, c in enumerate(event.context, start=1)),
        *(
            ("perspectives", i, f"{p.label} {p.summary}")
            for i, p in enumerate(event.perspectives, start=1)
        ),
    ]
    for layer, index, text in spoken_layers:
        report.extend(f"{layer}[{index}]", validators.check_voice_vocabulary(text))

    sources = [info.title, *(f.text for f in event.facts), *(c.text for c in event.context)]
    notes = [item.note for item in event.evidence]
    banned = validators.banned_phrases()
    for tone, telling in event.tellings.items():
        where = f"tellings.{tone}"
        report.extend(where, validators.check_beats(telling.beats, spoken_by_slot))
        if telling.voice:
            report.extend(f"{where}.voice", voice_problems(telling.voice, tone, info.tone_class))
        for index, beat in enumerate(telling.beats, start=1):
            beat_where = f"{where}.beats[{index}]"
            report.extend(beat_where, validators.check_faithfulness(beat, sources))
            report.extend(beat_where, validators.check_copy(beat, notes))
            report.extend(beat_where, validators.check_banned_phrases(beat, banned))
            report.extend(beat_where, validators.check_voice_vocabulary(beat))
        report.extend(
            where,
            validators.check_closing(
                telling.closing_kind, telling.closing_text, sources, info.tone_class
            ),
        )
        report.extend(f"{where}.closing_text", validators.check_copy(telling.closing_text, notes))
        report.extend(
            f"{where}.closing_text", validators.check_banned_phrases(telling.closing_text, banned)
        )
        report.extend(
            f"{where}.closing_text", validators.check_voice_vocabulary(telling.closing_text)
        )
    return report


def publisher_key(name: str) -> str:
    """One identity per publisher, so "BBC" and "bbc" count once everywhere."""
    return slugify(name)


def _check_synthetic_flag(title: str, synthetic: bool, report: Report) -> None:
    """Keep test fixtures and real events from being loaded as each other."""
    looks_synthetic = "SYNTHETIC" in title.upper()
    if synthetic and not looks_synthetic:
        report.errors.append("--synthetic requires SYNTHETIC EVENT in the event title.")
    if looks_synthetic and not synthetic:
        report.errors.append("a SYNTHETIC event must be loaded with --synthetic.")


def _check_proverbs(event: CuratedEvent, report: Report) -> dict[str, str]:
    """Every mapped proverb must exist and be servable; return slot -> spoken form."""
    spoken_by_slot = {}
    for slot, mapping in event.proverbs.items():
        if not re.fullmatch(r"P[1-9][0-9]*", slot):
            report.errors.append(f"proverbs.{slot}: slot names look like P1, P2.")
            continue
        proverb = Proverb.objects.filter(pk=mapping.id).first()
        if proverb is None:
            report.errors.append(f"proverbs.{slot}: no proverb with id {mapping.id!r}.")
            continue
        if not Proverb.objects.servable().filter(pk=proverb.pk).exists():
            report.errors.append(
                f"proverbs.{slot}: {mapping.id} is {proverb.verification_status}"
                f"{'' if proverb.tone_ok else ' and not tone approved'}; only servable "
                "(verified, tone-approved) proverbs may be used."
            )
            continue
        spoken_by_slot[slot] = proverb.spoken_form
    return spoken_by_slot


def load_curated_event(
    event: CuratedEvent, *, synthetic: bool = False, replace: bool = False
) -> LoadResult:
    """Validate, then write the whole event atomically or not at all."""
    report = validate_curated_event(event, synthetic=synthetic)
    cluster_key = f"curated:{slugify(event.event.title)}"[:64]
    existing = Story.objects.filter(cluster_key=cluster_key).first()
    if existing and not replace:
        report.errors.append(
            f"a story from this event already exists ({existing.pk}); use --replace to reload it."
        )
    report.errors.extend(_shared_evidence_conflicts(event, existing))
    if not report.ok:
        _trace(None, StageTrace.Status.FAILED, event, error="\n".join(report.errors))
        raise CuratedEventError(report)

    try:
        with transaction.atomic():
            story = _write_story(event, existing, cluster_key, synthetic)
            articles = _write_evidence(event)
            _write_layers(event, story, articles)
            _write_tellings(event, story)
            story.publish()
    except DjangoValidationError as error:
        # Publication invariants are the last gate; the transaction has rolled back.
        report.errors.extend(error.messages)
        _trace(None, StageTrace.Status.FAILED, event, error="\n".join(report.errors))
        raise CuratedEventError(report) from error
    _trace(story, StageTrace.Status.OK, event)
    return LoadResult(story=story, warnings=report.warnings)


def _shared_evidence_conflicts(event: CuratedEvent, existing: Story | None) -> list[str]:
    """Refuse to rewrite a note that another story already shows as its source."""
    problems = []
    for item in event.evidence:
        digest = url_digest(canonical_url(item.url))
        article = Article.objects.filter(
            url_hash=digest, evidence_kind=Article.EvidenceKind.CURATED
        ).first()
        if article is None or article.snippet == item.note:
            continue
        others = (
            Story.objects.filter(
                Q(facts__articles=article)
                | Q(context_items__articles=article)
                | Q(perspectives__articles=article)
            )
            .exclude(pk=existing.pk if existing else None)
            .distinct()
            .values_list("pk", flat=True)
        )
        if others:
            problems.append(
                f"evidence {item.key}: this article is already cited by story "
                f"{', '.join(others)} with a different note; reuse that note so its "
                "sources do not change."
            )
    return problems


def _write_story(
    event: CuratedEvent, existing: Story | None, cluster_key: str, synthetic: bool
) -> Story:
    """Reuse the existing row on --replace so user memory keeps pointing at it."""
    info = event.event
    story = existing or Story(cluster_key=cluster_key)
    if existing:
        existing.facts.all().delete()
        existing.context_items.all().delete()
        existing.perspectives.all().delete()
        existing.tellings.all().delete()
    story.handle = info.title
    story.region = info.region
    story.tone_class = info.tone_class
    story.themes = info.themes
    story.is_synthetic = synthetic
    story.status = Story.Status.DRAFT
    story.published_at = None
    story.rejection_reasons = []
    story.save()
    return story


def _write_evidence(event: CuratedEvent) -> dict[str, Article]:
    """One inactive, never-fetched SourceFeed per publisher; one Article per evidence key."""
    articles = {}
    for item in event.evidence:
        feed_url = f"curated://{publisher_key(item.publisher)}"
        source, _ = SourceFeed.objects.get_or_create(
            feed_url=feed_url,
            defaults={
                "name": item.publisher,
                "region": event.event.region,
                "language": item.language,
                "terms_url": feed_url,
                "attribution_text": item.publisher,
                "active": False,
                "use_policy": SourceFeed.UsePolicy.BLOCKED,
            },
        )
        clean = canonical_url(item.url)
        digest = url_digest(clean)
        values = {
            "source": source,
            "evidence_kind": Article.EvidenceKind.CURATED,
            "url_clean": clean,
            "title": item.headline,
            "snippet": item.note,
            "published_at": datetime.combine(item.published_on, datetime.min.time(), UTC),
            "language": item.language,
            "region_tags": [event.event.region],
        }
        article = Article.objects.filter(url_hash=digest).first()
        if article is None:
            article = Article.objects.create(url_hash=digest, **values)
        elif article.evidence_kind == Article.EvidenceKind.CURATED:
            for name, value in values.items():
                setattr(article, name, value)
            article.save()
        articles[item.key] = article
    return articles


def _write_layers(event: CuratedEvent, story: Story, articles: dict[str, Article]) -> None:
    for order, fact in enumerate(event.facts, start=1):
        row = StoryFact.objects.create(story=story, order=order, text=fact.text)
        row.articles.set(articles[key] for key in fact.evidence)
    for order, item in enumerate(event.context, start=1):
        row = StoryContext.objects.create(story=story, order=order, kind=item.kind, text=item.text)
        row.articles.set(articles[key] for key in item.evidence)
    publishers = {articles[key].source_id for p in event.perspectives for key in p.evidence}
    if len(publishers) < 2:
        return
    for order, item in enumerate(event.perspectives, start=1):
        row = StoryPerspective.objects.create(
            story=story, order=order, label=item.label, summary=item.summary
        )
        row.articles.set(articles[key] for key in item.evidence)


def _write_tellings(event: CuratedEvent, story: Story) -> None:
    for tone in TONES:
        telling_in = event.tellings.get(tone)
        if telling_in is None:
            continue
        telling = StoryTelling.objects.create(
            story=story,
            tone=tone,
            closing_kind=telling_in.closing_kind,
            moral=telling_in.closing_text,
            voice_style=telling_in.voice or "",
            status=StoryTelling.Status.PUBLISHED,
            is_curated=True,
            checker_report={"source": "curated", "validators": "passed"},
        )
        for order, text in enumerate(telling_in.beats, start=1):
            TellingBeat.objects.create(telling=telling, order=order, text_template=text)
        for slot, mapping in event.proverbs.items():
            TellingProverb.objects.create(
                telling=telling, proverb_id=mapping.id, slot=slot, role=mapping.role
            )


def _trace(story: Story | None, status: str, event: CuratedEvent, error: str = "") -> None:
    """Record the load outside the data transaction so failures are audited too."""
    StageTrace.objects.create(
        story=story,
        stage="curated_load",
        status=status,
        input_summary=f"{event.event.title} ({len(event.evidence)} evidence, "
        f"{len(event.tellings)} tellings)",
        output_summary=story.pk if story else "",
        error=error[:4000],
    )
