"""Tool logic for the MCP server. Plain synchronous Django code over precomputed data.

No handler calls an LLM. Every story read goes through Story.objects.listable(), and
every memory write is skipped for guests. server.py runs these off the event loop and
turns FriendlyError into an `isError` result the listener can act on.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import F, Func, TextField, Value

from apps.memory import services as memory
from apps.memory.models import EndUser, StoryEncounter
from apps.news.models import Article
from apps.stories.models import Story, StoryContext, StoryTelling
from apps.wisdom.rendering import RenderingError, render_beat

from . import schemas
from .voice import friendly_error, human_date, join_within, options, paginate

PAGE_SIZE = 5
CONTEXT_LABELS = {
    StoryContext.Kind.BACKGROUND: "Some background",
    StoryContext.Kind.WHY_IT_MATTERS: "Why it matters",
    StoryContext.Kind.CONSEQUENCE: "What it could mean",
}


class FriendlyError(Exception):
    """A problem the listener can fix, described in plain words with a next step."""

    def __init__(self, kind: str, spoken: str, next_options: Iterable[str] = ()) -> None:
        super().__init__(spoken)
        self.kind = kind
        self.spoken = spoken
        self.next_options = options(*next_options)

    @classmethod
    def known(cls, kind: str, hint: str | None = None) -> FriendlyError:
        """One of the standard messages in voice.FRIENDLY_ERRORS."""
        spoken, next_options = friendly_error(kind, hint)
        return cls(kind, spoken, next_options)


# Lookups ------------------------------------------------------------------------------


def published_stories():
    return Story.objects.listable().filter(status=Story.Status.PUBLISHED)


def find_story(story_id: str) -> Story:
    story = published_stories().filter(pk=story_id).first()
    if story is None:
        raise FriendlyError.known("unknown_story")
    return story


def resolve_story(user: EndUser | None, story_id: str | None) -> Story:
    """The named story, else the one in this listener's session, else a helpful re-prompt.

    Alexa+ asks that missing or expired context never dead-ends the conversation.
    """
    if story_id:
        return find_story(story_id)
    last = memory.get_session_context(user).last_story_id if user else None
    if last:
        return find_story(last)
    raise FriendlyError.known("which_story")


def listening_tone(user: EndUser | None, story: Story) -> str:
    """The tone the listener heard, then their preference, then balanced."""
    if user is None:
        return memory.DEFAULT_TONE
    encounter = StoryEncounter.objects.filter(user=user, story=story).first()
    return (encounter.tone_heard if encounter else "") or memory.preferred_tone(user)


def explore(user: EndUser | None, story: Story, layer: str, *defaults: str) -> list[str]:
    """Record the layer first, so the next suggestion never repeats what was just heard.

    Guests get the defaults; nothing is recorded for them.
    """
    if user is None:
        return options(*defaults)
    memory.mark_layer_explored(user, story, layer)
    suggestion = memory.next_layer_suggestion(user, story)
    heard = {memory.LAYER_LABELS[name] for name in memory.explored_layers(user, story)}
    fresh = [label for label in defaults if label not in heard]
    next_options = options(suggestion.label if suggestion else None, *fresh) or ["another story"]
    memory.update_session_context(user, last_story_id=story.pk, last_options=next_options)
    return next_options


STEP_LABELS = {
    "tale": "TALE",
    "proverbs": "PROVERBS",
    "facts": "FACTS",
    "context": "CONTEXT",
    "perspectives": "PERSPECTIVES",
    "sources": "SOURCES",
}


def card_fields(
    user: EndUser | None, story: Story, current: str, telling: StoryTelling | None = None
) -> dict:
    """story_id, title and the progress strip. Call after memory is updated.

    The closing step is labelled MORAL only when the telling's closing is a moral.
    """
    if telling is None:
        telling = memory.published_telling(story, listening_tone(user, story))
    heard = memory.explored_layers(user, story) if user else set()
    is_moral = bool(telling and telling.closing_kind == StoryTelling.ClosingKind.MORAL)
    labels = {**STEP_LABELS, "closing": "MORAL" if is_moral else "REFLECTION"}
    steps = [
        schemas.LayerStep(
            key=layer,
            label=labels[layer],
            state="current" if layer == current else "heard" if layer in heard else "ahead",
        )
        for layer in memory.available_layers(story, telling.tone if telling else None)
    ]
    return {
        "story_id": story.pk,
        "title": story.handle,
        "progress": schemas.LayerProgress(current=current, steps=steps),
    }


def proverb_details(telling: StoryTelling | None) -> list[schemas.ProverbDetail]:
    """Every servable proverb in a telling, in slot order; unservable ones are never shown."""
    if telling is None:
        return []
    links = sorted(
        telling.proverb_links.select_related("proverb"), key=lambda link: int(link.slot[1:])
    )
    return [
        schemas.ProverbDetail(
            slot=link.slot,
            spoken_form=link.proverb.spoken_form,
            original_text=link.proverb.original_text,
            language=link.proverb.language,
            culture=link.proverb.culture,
            meaning=link.proverb.meaning_note,
            source_citation=link.proverb.source_citation,
            verification_status=link.proverb.verification_status,
        )
        for link in links
        if link.proverb_is_servable
    ]


def closing_label(telling: StoryTelling | None) -> str | None:
    if telling and telling.closing_kind != StoryTelling.ClosingKind.NONE and telling.moral:
        return f"the {telling.closing_kind}"
    return None


# Finding stories ------------------------------------------------------------------------


def search_events(
    user: EndUser | None, *, query: str, region: str | None = None, page: int = 1
) -> schemas.StoryList:
    """Full-text search over titles, facts, tale text and themes, best match first."""
    query = query.strip()
    if not query:
        raise FriendlyError(
            "empty_query", "What would you like a story about?", ["today's stories"]
        )
    stories = published_stories()
    if region:
        stories = stories.filter(region__icontains=region.strip())
    themes = Func(F("themes"), Value(" "), function="array_to_string", output_field=TextField())
    vector = (
        SearchVector("handle", weight="A", config="english")
        + SearchVector(themes, weight="A", config="english")
        + SearchVector("facts__text", weight="B", config="english")
        + SearchVector("tellings__beats__text_template", weight="C", config="english")
    )
    search = SearchQuery(query, search_type="websearch", config="english")
    best: dict[str, float] = {}
    for story_id, rank in (
        stories.annotate(document=vector, rank=SearchRank(vector, search))
        .filter(document=search)
        .values_list("pk", "rank")
    ):
        best[story_id] = max(rank, best.get(story_id, 0.0))
    ranked = sorted(best, key=lambda story_id: -best[story_id])
    if not ranked:
        where = f" in {region}" if region else ""
        raise FriendlyError(
            "no_results",
            f"I couldn't find a story about {query}{where}. "
            "You could hear today's stories, or try another topic.",
            ["today's stories"],
        )
    by_id = published_stories().in_bulk(ranked)
    return _story_page(user, [by_id[i] for i in ranked if i in by_id], page, found=query)


def get_briefing(
    user: EndUser | None, *, region: str | None = None, page: int = 1
) -> schemas.StoryList:
    """Recent stories, in the listener's preferred region when they have one."""
    preferred = memory.get_preferences(user).regions if user else []
    chosen_region = region or (preferred[0] if preferred else None)
    stories = published_stories()
    if chosen_region:
        stories = stories.filter(region__icontains=chosen_region.strip())
    stories = list(stories.order_by("-published_at")[: PAGE_SIZE * 10])
    if not stories:
        raise FriendlyError(
            "no_results",
            f"I don't have stories from {chosen_region} yet. "
            "You could hear stories from everywhere.",
            ["stories from everywhere"],
        )
    return _story_page(user, stories, page, found=None)


def _story_page(
    user: EndUser | None, stories: list[Story], page: int, *, found: str | None
) -> schemas.StoryList:
    result = paginate(stories, page, PAGE_SIZE)
    chunk, has_more = result.items, result.has_more
    if not chunk:
        raise FriendlyError(
            "no_more_results", "That's all the stories I have for now.", ["today's stories"]
        )
    titles = [story.handle for story in chunk]
    intro = f"Here's what I found about {found}:" if found else "Here are today's stories:"
    sentences = [intro, *(f"{title}." for title in titles), "Which one would you like to hear?"]
    spoken = join_within(sentences, more="Which one would you like to hear?")
    next_options = options(*titles[:4], result.next_page_hint)
    if user is not None:
        memory.update_session_context(user, last_options=next_options)
    return schemas.StoryList(
        spoken=spoken,
        next_options=next_options,
        stories=[
            schemas.StoryListing(story_id=story.pk, title=story.handle, region=story.region)
            for story in chunk
        ],
        page=page,
        has_more=has_more,
    )


# The tale ---------------------------------------------------------------------------


def tell_tale(
    user: EndUser | None,
    *,
    story_id: str | None = None,
    beat: int | None = None,
    tone: str | None = None,
) -> schemas.TaleBeat:
    """One beat of the tale, rendered with verified proverbs; progress is remembered.

    With no beat, a listener continues where they stopped, in the tone they were hearing;
    otherwise the tone is the argument, then their preference, then balanced.
    """
    story = resolve_story(user, story_id)
    encounter = StoryEncounter.objects.filter(user=user, story=story).first() if user else None
    if tone is None and encounter and encounter.tone_heard:
        wanted = encounter.tone_heard
    else:
        wanted = memory.preferred_tone(user, tone) if user else (tone or memory.DEFAULT_TONE)
    if beat is None:
        resuming = encounter and encounter.last_beat and not encounter.tale_completed
        beat = encounter.last_beat + 1 if resuming and encounter.tone_heard == wanted else 1
    tellings = {t.tone: t for t in story.tellings.filter(status=StoryTelling.Status.PUBLISHED)}
    order = [
        t for t in dict.fromkeys((wanted, memory.DEFAULT_TONE, *memory.TONES)) if t in tellings
    ]
    if not order:
        raise FriendlyError(
            "tale_unavailable",
            "I can't tell that tale right now. You can still hear what actually happened.",
            ["the facts"],
        )

    first_total = tellings[order[0]].beats.count()
    if beat > first_total:
        raise FriendlyError(
            "beat_out_of_range",
            f"That tale has {first_total} parts. Shall I start it from the beginning?",
            ["start the tale", "the facts"],
        )

    for tone_name in order:
        telling = tellings[tone_name]
        beats = list(telling.beats.order_by("order"))
        if beat > len(beats):
            continue
        try:
            rendered = render_beat(beats[beat - 1])
        except RenderingError:
            # A proverb may have been disputed after publication; never speak it.
            continue
        return _beat_result(user, story, telling, rendered, beat, len(beats))
    raise FriendlyError(
        "tale_unavailable",
        "I can't tell that part of the tale right now. You can still hear what actually happened.",
        ["the facts", "the sources"],
    )


def _beat_result(user, story, telling, rendered, beat, total) -> schemas.TaleBeat:
    has_more = beat < total
    if has_more:
        next_options = options("continue", "the facts")
    else:
        next_options = options(
            closing_label(telling),
            "the proverb explained" if telling.proverb_links.exists() else None,
            "the facts",
        )
    if user is not None:
        memory.record_beat(user, story, telling.tone, beat)
        memory.update_session_context(user, last_story_id=story.pk, last_options=next_options)
    return schemas.TaleBeat(
        spoken=rendered.text,
        next_options=next_options,
        **card_fields(user, story, "tale", telling),
        beat=beat,
        beats_total=total,
        has_more=has_more,
        tone_served=telling.tone,
        voice_style=telling.voice.key,
        voice_name=telling.voice.name,
        text=rendered.text,
        proverbs_used=[
            schemas.ProverbFlag(slot=ref.slot, culture=ref.culture, spoken_form=ref.spoken_form)
            for ref in rendered.proverbs
        ],
    )


def get_moral(user: EndUser | None, *, story_id: str | None = None) -> schemas.ClosingThought:
    """The tale's closing thought: a moral, a neutral reflection, or none."""
    story = resolve_story(user, story_id)
    telling = memory.published_telling(story, listening_tone(user, story))
    cultures = _proverb_cultures(telling)
    proverb_note = f"The tale carried a proverb from {_people(cultures[0])}." if cultures else ""
    if closing_label(telling):
        kind, text = telling.closing_kind, telling.moral
        spoken = text
    else:
        kind, text = StoryTelling.ClosingKind.NONE, ""
        spoken = "This tale ends without a lesson of its own; it is left for you to reflect on."
    next_options = explore(user, story, "closing", "the facts", "the sources")
    return schemas.ClosingThought(
        spoken=spoken,
        next_options=next_options,
        **card_fields(user, story, "closing", telling),
        proverbs=proverb_details(telling),
        closing_kind=kind,
        text=text,
        proverb_note=proverb_note,
    )


def explain_proverb(
    user: EndUser | None, *, story_id: str | None = None, which: int = 1
) -> schemas.ProverbExplanation:
    """Culture, meaning, original wording and source of a proverb in the tale."""
    story = resolve_story(user, story_id)
    telling = memory.published_telling(story, listening_tone(user, story))
    links = sorted(
        telling.proverb_links.select_related("proverb") if telling else [],
        key=lambda link: int(link.slot[1:]),
    )
    if not links:
        next_options = explore(user, story, "proverbs", "the facts")
        return schemas.ProverbExplanation(
            spoken="This tale didn't use a proverb. You can hear what actually happened instead.",
            next_options=next_options,
            **card_fields(user, story, "proverbs", telling),
            has_proverb=False,
            which=which,
            proverbs_total=0,
        )
    if which > len(links):
        raise FriendlyError(
            "proverb_out_of_range",
            f"This tale has {len(links)} proverb{'s' if len(links) > 1 else ''}. "
            "Shall I explain the first one?",
            ["the proverb explained"],
        )
    link = links[which - 1]
    if not link.proverb_is_servable:
        raise FriendlyError(
            "proverb_unavailable",
            "I can't share that proverb right now. You can hear what actually happened instead.",
            ["the facts"],
        )
    proverb = link.proverb
    spoken = join_within(
        [
            f"This proverb comes from {_people(proverb.culture)}, in {proverb.language}.",
            f"It means: {proverb.meaning_note}",
        ],
        more="",
    )
    next_options = explore(user, story, "proverbs", "the facts", "the sources")
    return schemas.ProverbExplanation(
        spoken=spoken,
        next_options=next_options,
        **card_fields(user, story, "proverbs", telling),
        proverbs=proverb_details(telling),
        has_proverb=True,
        which=which,
        proverbs_total=len(links),
        spoken_form=proverb.spoken_form,
        original_text=proverb.original_text,
        language=proverb.language,
        culture=proverb.culture,
        meaning=proverb.meaning_note,
        source_citation=proverb.source_citation,
        verification_status=proverb.verification_status,
    )


def _proverb_cultures(telling: StoryTelling | None) -> list[str]:
    if telling is None:
        return []
    links = telling.proverb_links.select_related("proverb").order_by("slot")
    return list(dict.fromkeys(link.proverb.culture for link in links))


def _people(culture: str) -> str:
    """'Hausa' becomes 'the Hausa people'; a descriptive culture name is kept as it is."""
    return f"the {culture}" if re.search(r"\bpeoples?\b", culture) else f"the {culture} people"


# Truth layers -------------------------------------------------------------------------


def get_facts(user: EndUser | None, *, story_id: str | None = None) -> schemas.FactList:
    story = resolve_story(user, story_id)
    facts = list(story.facts.prefetch_related("articles__source"))
    items = [schemas.FactItem(text=fact.text, sources=_refs(fact.articles.all())) for fact in facts]
    publishers = _publishers(fact.articles.all() for fact in facts)
    attribution = f"Reported by {_spoken_list(publishers)}." if publishers else ""
    spoken = join_within([fact.text for fact in facts], more="There's more if you'd like it.")
    next_options = explore(user, story, "facts", "the background", "the sources")
    return schemas.FactList(
        spoken=f"{spoken} {attribution}".strip(),
        next_options=next_options,
        **card_fields(user, story, "facts"),
        facts=items,
    )


def get_context(user: EndUser | None, *, story_id: str | None = None) -> schemas.ContextList:
    story = resolve_story(user, story_id)
    rows = list(story.context_items.prefetch_related("articles__source"))
    items = [
        schemas.ContextItem(
            kind=row.kind,
            label=CONTEXT_LABELS.get(row.kind, "Context"),
            text=row.text,
            sources=_refs(row.articles.all()),
        )
        for row in rows
    ]
    if items:
        spoken = join_within(
            [f"{item.label}: {item.text}" for item in items], more="There's more if you'd like it."
        )
    else:
        spoken = "I don't have more background on this story yet. You can hear the sources instead."
    next_options = explore(user, story, "context", "different perspectives", "the sources")
    return schemas.ContextList(
        spoken=spoken,
        next_options=next_options,
        context=items,
        **card_fields(user, story, "context"),
    )


def get_perspectives(
    user: EndUser | None, *, story_id: str | None = None
) -> schemas.PerspectiveList:
    story = resolve_story(user, story_id)
    rows = list(story.perspectives.prefetch_related("articles__source"))
    items = [
        schemas.PerspectiveItem(
            label=row.label, summary=row.summary, sources=_refs(row.articles.all())
        )
        for row in rows
    ]
    if items:
        spoken = join_within(
            [f"{item.label}: {item.summary}" for item in items],
            more="There are more views if you'd like them.",
        )
    else:
        spoken = (
            "The sources for this story don't show clearly different views, so I won't "
            "invent any. You can hear the sources instead."
        )
    next_options = explore(user, story, "perspectives", "the sources", "the facts")
    return schemas.PerspectiveList(
        spoken=spoken,
        next_options=next_options,
        perspectives=items,
        **card_fields(user, story, "perspectives"),
    )


def get_sources(user: EndUser | None, *, story_id: str | None = None) -> schemas.SourceList:
    """Evidence cards, one per article, noting which layers each one supports."""
    story = resolve_story(user, story_id)
    cards: dict[int, dict] = {}
    layers = (
        ("facts", story.facts.prefetch_related("articles__source")),
        ("context", story.context_items.prefetch_related("articles__source")),
        ("perspectives", story.perspectives.prefetch_related("articles__source")),
    )
    for layer, rows in layers:
        for row in rows:
            for article in row.articles.all():
                card = cards.setdefault(article.pk, {"article": article, "supports": []})
                if layer not in card["supports"]:
                    card["supports"].append(layer)
    sources = [_source_card(card["article"], card["supports"]) for card in cards.values()]
    publishers = list(dict.fromkeys(card.publisher for card in sources))
    if publishers:
        count = len(sources)
        spoken = (
            f"This story draws on {count} source{'s' if count != 1 else ''}, "
            f"from {_spoken_list(publishers)}."
        )
    else:
        spoken = "I don't have sources to share for this story."
    next_options = explore(user, story, "sources", "the facts", "another story")
    return schemas.SourceList(
        spoken=spoken,
        next_options=next_options,
        sources=sources,
        **card_fields(user, story, "sources"),
    )


def _source_card(article: Article, supports: list[str]) -> schemas.SourceCard:
    return schemas.SourceCard(
        publisher=article.source.name,
        headline=article.title,
        date=human_date(article.published_at),
        supports=supports,
        url=article.url_clean if settings.INCLUDE_SOURCE_URLS else None,
    )


def _refs(articles: Iterable[Article]) -> list[schemas.SourceRef]:
    return [
        schemas.SourceRef(publisher=article.source.name, date=human_date(article.published_at))
        for article in articles
    ]


def _publishers(groups: Iterable[Iterable[Article]]) -> list[str]:
    return list(dict.fromkeys(article.source.name for group in groups for article in group))


def _spoken_list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


# The listener's own memory ----------------------------------------------------------


def require_listener(user: EndUser | None) -> EndUser:
    """Memory needs an identity; guests are told how to get one, never dead-ended."""
    if user is None:
        raise FriendlyError.known("needs_account")
    return user


def save_for_later(user: EndUser | None, *, story_id: str | None = None) -> schemas.SaveResult:
    listener = require_listener(user)
    story = resolve_story(listener, story_id)
    memory.save_for_later(listener, story)
    suggestion = memory.next_layer_suggestion(listener, story)
    next_options = options(suggestion.label if suggestion else None, "my saved stories")
    memory.update_session_context(listener, last_story_id=story.pk, last_options=next_options)
    return schemas.SaveResult(
        spoken=f"Saved {story.handle}. Ask for your saved stories any time.",
        next_options=next_options,
        story_id=story.pk,
        title=story.handle,
        saved=True,
    )


def get_saved_stories(user: EndUser | None) -> schemas.SavedList:
    """Saved stories plus the latest unfinished tale, each with where to pick up."""
    listener = require_listener(user)
    progress = memory.get_saved_stories(listener)
    stories = [
        schemas.SavedStory(
            story_id=item.story_id,
            title=item.handle,
            saved=item.saved,
            tone=item.tone,
            last_beat=item.last_beat,
            beats_total=item.beats_total,
            tale_completed=item.tale_completed,
            resume_hint=item.resume_hint,
        )
        for item in progress
    ]
    if not stories:
        return schemas.SavedList(
            spoken="You haven't saved any stories yet. While listening, say save this story.",
            next_options=options("today's stories"),
            stories=[],
        )
    count = len(stories)
    sentences = [f"You have {count} stor{'ies' if count != 1 else 'y'} waiting."]
    sentences += [f"{story.title}: {story.resume_hint}." for story in stories]
    spoken = join_within(sentences, more="Which one would you like?")
    first = stories[0]
    next_options = options(
        first.resume_hint if not first.tale_completed else None,
        *(story.title for story in stories[:3]),
        "today's stories",
    )
    memory.update_session_context(listener, last_story_id=first.story_id, last_options=next_options)
    return schemas.SavedList(spoken=spoken, next_options=next_options, stories=stories)


def set_preferences(
    user: EndUser | None,
    *,
    tone: str | None = None,
    regions: list[str] | None = None,
    topics: list[str] | None = None,
    reset: bool = False,
) -> schemas.PreferencesResult:
    """Change only what was asked for. "Start over" clears the conversation, not history."""
    listener = require_listener(user)
    if not reset and tone is None and regions is None and topics is None:
        raise FriendlyError(
            "nothing_to_change",
            "What would you like to change? I can tell tales in a light, balanced or serious "
            "tone, or focus on a region.",
            ["serious tone", "stories from everywhere"],
        )
    if reset:
        memory.reset_context(listener)
    try:
        preferences = memory.update_preferences(listener, tone=tone, regions=regions, topics=topics)
    except memory.MemoryInputError as error:
        raise FriendlyError(
            "unknown_topic",
            "I don't know that topic yet. You could try community, health, leadership or trade.",
            ["today's stories"],
        ) from error
    confirmations = ["Starting fresh."] if reset else []
    if tone is not None:
        confirmations.append(f"I'll tell tales in a {tone} tone.")
    if regions is not None:
        confirmations.append(
            f"I'll focus on stories from {' and '.join(preferences.regions)}."
            if preferences.regions
            else "I'll bring stories from everywhere."
        )
    if topics is not None:
        confirmations.append(
            f"I'll look for stories about {' and '.join(t.replace('_', ' ') for t in topics)}."
            if topics
            else ""
        )
    confirmations.append("What would you like to hear?")
    return schemas.PreferencesResult(
        spoken=" ".join(part for part in confirmations if part),
        next_options=options("today's stories", "my saved stories"),
        tone=preferences.tone,
        regions=preferences.regions,
        topics=preferences.topics,
        reset=reset,
    )
