"""The editorial pipeline: a news article in, a published Greeo story out.

    article -> read its text -> establish facts, context and perspectives
            -> choose proverbs by meaning -> write each allowed tone
            -> check (rules, then an editor model) -> revise once -> check -> publish

Every model call goes through the LLM gateway (budgeted, audited) and every stage is
recorded as a StageTrace. A story is published only if at least one telling passes all
checks; Story.publish() is the final gate. Every layer (facts, context, perspectives,
sources) comes from the article itself, never from a model's own knowledge.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.models import PipelineRun, StageTrace
from apps.llm.client import LLMGateway
from apps.llm.exceptions import LLMError
from apps.news.article import ArticleFetchError, ArticleText, fetch_article_text
from apps.news.models import Article, SourceFeed
from apps.wisdom.rendering import fill_slots
from apps.wisdom.services import ChosenProverb, choose_proverbs
from apps.wisdom.themes import theme_vocabulary

from . import validators
from .composition import TellingDraft, split_tale, used_slots
from .drafts import EstablishedFacts, Fact, TellingCheck
from .models import (
    Story,
    StoryContext,
    StoryFact,
    StoryPerspective,
    StoryTelling,
    TellingBeat,
    TellingProverb,
)
from .voices import voice_for

logger = logging.getLogger(__name__)

TONES = ("light", "balanced", "serious")
TARGET_WORDS = 250
MAX_WORDS = 320  # five beats of about 65 words
ARTICLE_CHARS = 12_000
ROLES = ("opening", "turn", "closing")  # proverb roles, in the order slots are offered
MONTHS = (
    "January February March April May June July August September October November December"
).split()

Fetch = Callable[[str], ArticleText]


@dataclass
class TellingResult:
    """One tone, checked: templates ready to store, or the problems that stopped it."""

    tone: str
    draft: TellingDraft
    beats: list[str]
    spoken_by_slot: dict[str, str]
    problems: list[str]
    first_draft_problems: list[str] = field(default_factory=list)
    # The editor model's verdict on the final draft: its reasoning and any issues.
    review: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclass
class PipelineResult:
    run_id: str
    published: list[str] = field(default_factory=list)
    rejected: dict[str, list[str]] = field(default_factory=dict)  # article url -> reasons


class StoryRejected(Exception):
    """The article did not become a publishable story; the reasons say why."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def run_pipeline(
    limit: int = 3,
    *,
    since_hours: int = 48,
    gateway: Any | None = None,
    fetch: Fetch = fetch_article_text,
) -> PipelineResult:
    """Turn up to `limit` recent, not-yet-told articles into published stories."""
    run = PipelineRun.objects.create()
    result = PipelineResult(run_id=str(run.pk))
    gateway = gateway or LLMGateway()
    for article in candidate_articles(limit, since_hours):
        try:
            story = build_story(article, run, gateway, fetch)
            result.published.append(story.pk)
        except StoryRejected as rejected:
            result.rejected[article.url_clean] = rejected.reasons
        except Exception as error:  # one bad article never stops the run
            logger.exception("Pipeline failed on %s", article.url_clean)
            result.rejected[article.url_clean] = [f"unexpected error: {error}"]
            _trace(run, None, "story", StageTrace.Status.FAILED, article.title, error=str(error))
    run.status = (
        PipelineRun.Status.OK
        if not result.rejected
        else PipelineRun.Status.PARTIAL
        if result.published
        else PipelineRun.Status.FAILED
    )
    run.finished_at = timezone.now()
    run.stats = {"published": len(result.published), "rejected": len(result.rejected)}
    run.save(update_fields=["status", "finished_at", "stats"])
    return result


def candidate_articles(limit: int, since_hours: int) -> list[Article]:
    """Newest articles from active feeds that no story has been made from yet."""
    told = Story.objects.filter(cluster_key__startswith="article:").values_list(
        "cluster_key", flat=True
    )
    told_hashes = {key.removeprefix("article:") for key in told}
    recent = (
        Article.objects.filter(
            source__active=True,
            source__use_policy=SourceFeed.UsePolicy.HEADLINE_SNIPPET_ONLY,
            evidence_kind=Article.EvidenceKind.NEWS_SNIPPET,
            published_at__gte=timezone.now() - timedelta(hours=since_hours),
        )
        .select_related("source")
        .order_by("-published_at")
    )
    picked = []
    for article in recent:
        if cluster_key(article).removeprefix("article:") not in told_hashes:
            picked.append(article)
        if len(picked) >= limit:
            break
    return picked


def cluster_key(article: Article) -> str:
    return f"article:{article.url_hash}"[:64]


def build_story(
    article: Article,
    run: PipelineRun,
    gateway: Any,
    fetch: Fetch,
    *,
    tones: tuple[str, ...] = TONES,
    extra_facts: tuple[str, ...] = (),
) -> Story:
    """All stages for one article; raises StoryRejected with reasons when it cannot pass."""
    body = _read(article, run, fetch)
    facts = _establish_facts(article, body, run, gateway)
    facts.facts += [
        Fact(id=f"F{len(facts.facts) + n}", text=text) for n, text in enumerate(extra_facts, 1)
    ]
    chosen = _choose_proverbs(facts, run, gateway)
    offered = {f"P{n}": item for n, item in enumerate(chosen, start=1)}
    sources = _sources(article, facts, chosen)

    tellings = []
    for tone in tones:
        if tone == "light" and facts.tone_class == "sensitive":
            continue
        telling = _tell(tone, facts, offered, sources, body, run, gateway)
        if telling.ok:
            tellings.append(telling)
    if not tellings:
        raise StoryRejected(["no telling passed the checks after one revision"])
    return _publish(article, run, facts, offered, tellings)


# Stages ----------------------------------------------------------------------------------


def _read(article: Article, run: PipelineRun, fetch: Fetch) -> str:
    """The article's own words when the publisher allows it; otherwise its feed snippet."""
    started = time.monotonic()
    try:
        text = fetch(article.url_clean)
    except ArticleFetchError as error:
        _trace(run, None, "read_article", StageTrace.Status.SKIPPED, article.title,
               output=f"snippet only: {error}", started=started)  # fmt: skip
        return f"{article.title}\n{article.snippet}"
    _trace(run, None, "read_article", StageTrace.Status.OK, article.title,
           output=f"{text.words} words", started=started)  # fmt: skip
    return text.text[:ARTICLE_CHARS]


def _establish_facts(
    article: Article, body: str, run: PipelineRun, gateway: Any
) -> EstablishedFacts:
    started = time.monotonic()
    vocabulary = theme_vocabulary()
    facts = gateway.generate_json(
        "establish_facts",
        {
            "pipeline_run_id": str(run.pk),
            "evidence": {
                "publisher": article.source.attribution_text,
                "date": article.published_at.date().isoformat() if article.published_at else "",
                "headline": article.title,
                "text": body,
            },
            "theme_vocabulary": vocabulary,
        },
        EstablishedFacts,
    )
    facts.themes = [theme for theme in facts.themes if theme in vocabulary]
    if len(facts.facts) < 2:
        _trace(run, None, "establish_facts", StageTrace.Status.FAILED, article.title,
               error="fewer than two facts", started=started)  # fmt: skip
        raise StoryRejected(["the article did not establish at least two facts"])
    _trace(run, None, "establish_facts", StageTrace.Status.OK, article.title,
           output=f"{len(facts.facts)} facts, {len(facts.context)} context, "
           f"{len(facts.perspectives)} perspectives, {facts.tone_class}",
           started=started)  # fmt: skip
    return facts


def _choose_proverbs(
    facts: EstablishedFacts, run: PipelineRun, gateway: Any
) -> list[ChosenProverb]:
    started = time.monotonic()
    chosen, reasoning = choose_proverbs(
        [fact.model_dump() for fact in facts.facts], facts.tone_class, gateway
    )
    _trace(run, None, "choose_proverbs", StageTrace.Status.OK, reasoning[:500],
           output=", ".join(c.proverb.id for c in chosen) or "none", started=started)  # fmt: skip
    return chosen


def _tell(
    tone: str,
    facts: EstablishedFacts,
    offered: dict[str, ChosenProverb],
    sources: list[str],
    body: str,
    run: PipelineRun,
    gateway: Any,
) -> TellingResult:
    """Write one tone, check it, and revise once with the exact problems found."""
    started = time.monotonic()
    voice = voice_for(tone, facts.tone_class)
    variables = {
        "pipeline_run_id": str(run.pk),
        "facts": [fact.model_dump() for fact in facts.facts],
        "context": [note.model_dump() for note in facts.context],
        "tone": tone,
        "tone_class": facts.tone_class,
        "voice": {"name": voice.name, "style": voice.style},
        "proverbs": {
            slot: {
                "text": item.proverb.spoken_form,
                "meaning": item.proverb.meaning_note,
                "culture": item.proverb.culture,
            }
            for slot, item in offered.items()
        },
        "target_words": TARGET_WORDS,
        "max_words": MAX_WORDS,
    }
    spoken = {slot: item.proverb.spoken_form for slot, item in offered.items()}

    def checked(draft: TellingDraft) -> TellingResult:
        result = check_draft(tone, draft, spoken, sources, body, facts.tone_class)
        if result.ok:  # the editor model reads only drafts that already pass the rules
            result.review = review_draft(draft, facts, run, gateway)
            result.problems += result.review["problems"]
        return result

    draft = gateway.generate_json("write_telling", variables, TellingDraft)
    result = checked(draft)
    if not result.ok:
        first = result.problems
        revision = {"tale": draft.tale, "closing_text": draft.closing_text, "problems": first}
        draft = gateway.generate_json(
            "write_telling", {**variables, "revision": revision}, TellingDraft
        )
        result = checked(draft)
        result.first_draft_problems = first
    _trace(run, None, f"tell_{tone}",
           StageTrace.Status.OK if result.ok else StageTrace.Status.FAILED,
           f"{tone} in the {voice.name} voice",
           output=f"{len(result.beats)} beats, proverbs {sorted(result.spoken_by_slot)}"
           + (" (revised)" if result.first_draft_problems else ""),
           error="; ".join(result.problems)[:4000], started=started)  # fmt: skip
    return result


def check_draft(
    tone: str,
    draft: TellingDraft,
    offered_spoken: dict[str, str],
    sources: list[str],
    body: str,
    tone_class: str,
) -> TellingResult:
    """Every deterministic check a telling must pass before it can be published."""
    spoken_by_slot, problems = used_slots(draft, offered_spoken)
    beats, split_problems = split_tale(draft.tale, spoken_by_slot)
    problems += split_problems
    problems += validators.check_beats(beats, spoken_by_slot)
    problems += validators.check_proverb_copies(draft.tale, spoken_by_slot)
    problems += validators.check_closing(
        draft.closing_kind, draft.closing_text, sources, tone_class
    )
    for number, beat in enumerate(beats, start=1):
        rendered = fill_slots(beat, spoken_by_slot) if not split_problems else beat
        problems += [f"beat {number}: {p}" for p in validators.check_faithfulness(beat, sources)]
        problems += [f"beat {number}: {p}" for p in validators.check_copy(rendered, [body])]
        problems += [f"beat {number}: {p}" for p in validators.check_voice_vocabulary(rendered)]
    if tone_class == "sensitive" and spoken_by_slot:
        problems.append("sensitive stories may not use proverbs.")
    return TellingResult(tone, draft, beats, spoken_by_slot, list(dict.fromkeys(problems)))


def review_draft(
    draft: TellingDraft, facts: EstablishedFacts, run: PipelineRun, gateway: Any
) -> dict[str, Any]:
    """An editor model reads the tale against its facts: imagery passes, invention does not.

    The rules catch names and numbers; this catches what they cannot, such as an invented
    cause, a side's claim told as truth, or an exaggeration that changes the facts. If the
    editor cannot be reached the telling is held back: unchecked tales are never told.
    """
    try:
        check = gateway.generate_json(
            "check_telling",
            {
                "pipeline_run_id": str(run.pk),
                "facts": [fact.model_dump() for fact in facts.facts],
                "context": [note.model_dump() for note in facts.context],
                "tale": draft.tale,
                "closing_text": draft.closing_text,
                "tone_class": facts.tone_class,
            },
            TellingCheck,
        )
    except LLMError as error:
        logger.warning("check_telling failed: %s", error)
        return {"reasoning": "", "issues": [], "problems": ["the editor check could not run."]}
    issues = [issue.model_dump() for issue in check.issues]
    return {
        "reasoning": check.reasoning,
        "issues": issues,
        "problems": [f'editor: "{issue["quote"]}": {issue["problem"]}' for issue in issues],
    }


@transaction.atomic
def _publish(
    article: Article,
    run: PipelineRun,
    facts: EstablishedFacts,
    offered: dict[str, ChosenProverb],
    tellings: list[TellingResult],
) -> Story:
    """Write the story and its passing tellings; Story.publish() is the final gate."""
    story = Story.objects.create(
        cluster_key=cluster_key(article),
        handle=(facts.title or article.title).strip().rstrip(".")[:120],
        tone_class=facts.tone_class,
        themes=facts.themes,
        region=article.region_tags[0] if article.region_tags else article.source.region,
        pipeline_run=run,
    )
    for order, fact in enumerate(facts.facts, start=1):
        StoryFact.objects.create(story=story, order=order, text=fact.text).articles.add(article)
    _store_layers(story, article, facts)

    roles = dict(zip(offered, ROLES, strict=False))
    for result in tellings:
        voice = voice_for(result.tone, facts.tone_class)
        telling = StoryTelling.objects.create(
            story=story,
            tone=result.tone,
            closing_kind=result.draft.closing_kind,
            moral=result.draft.closing_text[:200],
            voice_style=voice.key,
            status=StoryTelling.Status.PUBLISHED,
            revision_count=1 if result.first_draft_problems else 0,
            checker_report={
                "validators": "passed",
                "first_draft_problems": result.first_draft_problems,
                "editor": {k: v for k, v in result.review.items() if k != "problems"},
            },
        )
        for order, template in enumerate(result.beats, start=1):
            TellingBeat.objects.create(telling=telling, order=order, text_template=template)
        for slot in result.spoken_by_slot:
            TellingProverb.objects.create(
                telling=telling, proverb=offered[slot].proverb, slot=slot, role=roles[slot]
            )
    story.publish()
    _trace(run, story, "publish", StageTrace.Status.OK, article.title,
           output=f"{story.pk}: {', '.join(r.tone for r in tellings)}")  # fmt: skip
    return story


def add_missing_layers(
    *, gateway: Any | None = None, fetch: Fetch = fetch_article_text
) -> dict[str, str]:
    """Give stories published before context and perspectives existed those two layers.

    Each story's article is read again and its facts re-established; only the context
    and perspectives are kept, so the facts and tellings already published never change.
    Returns story id -> what was added, or why nothing was.
    """
    run = PipelineRun.objects.create()
    gateway = gateway or LLMGateway()
    outcome: dict[str, str] = {}
    stories = Story.objects.filter(
        cluster_key__startswith="article:", context_items__isnull=True, perspectives__isnull=True
    ).distinct()
    for story in stories:
        article = Article.objects.filter(facts__story=story).select_related("source").first()
        if article is None:
            outcome[story.pk] = "no article linked"
            continue
        try:
            body = _read(article, run, fetch)
            facts = _establish_facts(article, body, run, gateway)
        except (StoryRejected, LLMError) as error:
            outcome[story.pk] = f"skipped: {error}"
            continue
        with transaction.atomic():
            _store_layers(story, article, facts)
        outcome[story.pk] = f"{len(facts.context)} context, {len(facts.perspectives)} perspectives"
    run.status = PipelineRun.Status.OK
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at"])
    return outcome


def _store_layers(story: Story, article: Article, facts: EstablishedFacts) -> None:
    for order, note in enumerate(facts.context[:4], start=1):
        StoryContext.objects.create(
            story=story, order=order, kind=note.kind, text=note.text
        ).articles.add(article)
    for order, view in enumerate(facts.perspectives[:4], start=1):
        StoryPerspective.objects.create(
            story=story, order=order, label=view.label[:120], summary=view.summary
        ).articles.add(article)


# Helpers ---------------------------------------------------------------------------------


def _sources(article: Article, facts: EstablishedFacts, chosen: list[ChosenProverb]) -> list[str]:
    """What a telling may name: facts and context, headline and title, the proverbs' peoples."""
    fact_text = " ".join(fact.text for fact in facts.facts)
    return [
        *(fact.text for fact in facts.facts),
        *(note.text for note in facts.context),
        article.title,
        facts.title,
        *(item.proverb.culture for item in chosen),
        # Facts may write dates as 2026-10-01; a tale says 1 October 2026.
        *readable_dates(fact_text),
    ]


def readable_dates(text: str) -> list[str]:
    return [
        f"{int(day)} {MONTHS[int(month) - 1]} {year}"
        for year, month, day in re.findall(r"(\d{4})-(\d{2})-(\d{2})", text)
        if 1 <= int(month) <= 12
    ]


def _trace(
    run: PipelineRun | None,
    story: Story | None,
    stage: str,
    status: str,
    summary: str,
    *,
    output: str = "",
    error: str = "",
    started: float | None = None,
) -> None:
    StageTrace.objects.create(
        run=run,
        story=story,
        stage=stage,
        status=status,
        duration_ms=round((time.monotonic() - started) * 1000) if started else None,
        input_summary=summary[:500],
        output_summary=output[:500],
        error=error[:4000],
    )
