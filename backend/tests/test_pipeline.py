"""The editorial pipeline, end to end, with a scripted model and no network."""

from __future__ import annotations

from typing import Any

import pytest
from apps.core.models import PipelineRun, StageTrace
from apps.llm.exceptions import LLMProviderError
from apps.news.article import ArticleFetchError, ArticleText
from apps.news.models import Article, SourceFeed
from apps.stories.composition import TellingDraft
from apps.stories.drafts import (
    ContextNote,
    EstablishedFacts,
    Fact,
    PerspectiveNote,
    ProverbPick,
    ProverbRanking,
    TellingCheck,
    TellingIssue,
)
from apps.stories.models import Story, StoryTelling
from apps.stories.pipeline import add_missing_layers, run_pipeline
from django.utils import timezone

from tests.factories import ArticleFactory, ProverbFactory, SourceFeedFactory

pytestmark = pytest.mark.django_db

FACTS = [
    Fact(id="F1", text="SYNTHETIC: People in Veloria opened a footbridge over the Pell River."),
    Fact(id="F2", text="SYNTHETIC: Before the bridge, children crossed the Pell River by canoe."),
    Fact(id="F3", text="SYNTHETIC: Households in Veloria shared the work of building it."),
]

GOOD_TALE = (
    "Sit and listen. In Veloria the Pell River ran wide, and the children crossed it by "
    "canoe. The households gathered, and they built a footbridge together. As the Test "
    "culture say, {{P1}} Now the children cross on foot, and the river is no wall."
)


def draft(tale: str = GOOD_TALE, used: list[str] | None = None) -> TellingDraft:
    return TellingDraft(
        tale=tale,
        proverbs_used=["P1"] if used is None else used,
        closing_kind="reflection",
        closing_text="Some work is finished only when many hands share it.",
    )


class ScriptedGateway:
    """Answers each prompt from a script and records every call."""

    def __init__(
        self,
        *,
        tone_class: str = "neutral",
        tellings: list[TellingDraft] | None = None,
        reviews: list[TellingCheck | Exception] | None = None,
    ):
        self.tone_class = tone_class
        self.tellings = list(tellings or [])
        self.reviews = list(reviews or [])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.proverb = ProverbFactory(spoken_form="Many hands carry the bridge.")

    def generate_json(self, prompt_name: str, variables: dict[str, Any], output_model: type):
        self.calls.append((prompt_name, variables))
        if prompt_name == "establish_facts":
            return EstablishedFacts(
                title="Veloria opens its footbridge",
                reasoning="Synthetic.",
                facts=FACTS,
                context=[ContextNote(kind="background", text="SYNTHETIC: The river flooded.")],
                perspectives=[
                    PerspectiveNote(label="SYNTHETIC parents", summary="Parents say it is safer.")
                ],
                themes=["cooperation", "not_a_theme"],
                tone_class=self.tone_class,
                tone_class_reason="Synthetic.",
            )
        if prompt_name == "rerank_proverb":
            return ProverbRanking(
                reasoning="It is about shared work.", best=ProverbPick(id=self.proverb.id, why="x")
            )
        if prompt_name == "write_telling":
            return self.tellings.pop(0) if self.tellings else draft()
        if prompt_name == "check_telling":
            review = self.reviews.pop(0) if self.reviews else TellingCheck(reasoning="Faithful.")
            if isinstance(review, Exception):
                raise review
            return review
        raise AssertionError(f"unexpected prompt {prompt_name}")

    def prompts(self) -> list[str]:
        return [name for name, _ in self.calls]


def fetched(url: str) -> ArticleText:
    return ArticleText(url=url, text="SYNTHETIC article body about a footbridge.", words=7)


@pytest.fixture
def article() -> Article:
    source = SourceFeedFactory(
        active=True,
        use_policy=SourceFeed.UsePolicy.HEADLINE_SNIPPET_ONLY,
        attribution_text="Synthetic Gazette",
        region="Synthetic Region",
    )
    return ArticleFactory(
        source=source,
        evidence_kind=Article.EvidenceKind.NEWS_SNIPPET,
        title="SYNTHETIC: Footbridge opens in Veloria",
        published_at=timezone.now(),
    )


def test_an_article_becomes_a_published_story_with_three_tellings(article: Article) -> None:
    gateway = ScriptedGateway()

    result = run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    assert len(result.published) == 1 and result.rejected == {}
    story = Story.objects.get(pk=result.published[0])
    assert story.status == Story.Status.PUBLISHED
    assert story.handle == "Veloria opens its footbridge"
    assert story.themes == ["cooperation"]  # unknown themes are dropped
    assert story.cluster_key == f"article:{article.url_hash}"
    assert [fact.articles.get() for fact in story.facts.all()] == [article] * 3
    tellings = story.tellings.order_by("tone")
    assert [t.tone for t in tellings] == ["balanced", "light", "serious"]
    for telling in tellings:
        assert telling.status == StoryTelling.Status.PUBLISHED
        assert telling.beats.count() >= 3
        link = telling.proverb_links.get()
        assert (link.slot, link.role, link.proverb) == ("P1", "opening", gateway.proverb)
    assert (
        gateway.prompts()
        == ["establish_facts", "rerank_proverb"]
        + [
            "write_telling",
            "check_telling",
        ]
        * 3
    )
    assert [(c.kind, c.articles.get()) for c in story.context_items.all()] == [
        ("background", article)
    ]
    assert [p.label for p in story.perspectives.all()] == ["SYNTHETIC parents"]
    assert PipelineRun.objects.get(pk=result.run_id).status == PipelineRun.Status.OK
    stages = set(StageTrace.objects.values_list("stage", flat=True))
    assert {"read_article", "establish_facts", "choose_proverbs", "tell_light", "publish"} <= stages


def test_a_failing_draft_is_revised_once_with_its_problems(article: Article) -> None:
    quoted = draft(GOOD_TALE.replace("Sit and listen.", 'He said, "Sit and listen."'))
    gateway = ScriptedGateway(tellings=[quoted, draft()])

    result = run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    revision = gateway.calls[3][1]["revision"]
    assert any("quotation mark" in problem for problem in revision["problems"])
    telling = Story.objects.get(pk=result.published[0]).tellings.get(tone="light")
    assert telling.revision_count == 1
    assert telling.checker_report["first_draft_problems"]


def test_sensitive_stories_get_no_light_telling_and_no_proverbs(article: Article) -> None:
    plain = draft(GOOD_TALE.replace("As the Test culture say, {{P1}} ", ""), used=[])
    gateway = ScriptedGateway(tone_class="sensitive", tellings=[plain, plain])

    result = run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    story = Story.objects.get(pk=result.published[0])
    assert sorted(story.tellings.values_list("tone", flat=True)) == ["balanced", "serious"]
    assert "rerank_proverb" not in gateway.prompts()
    assert not story.tellings.filter(proverb_links__isnull=False).exists()


def test_an_article_whose_tellings_never_pass_is_not_published(article: Article) -> None:
    invented = draft(GOOD_TALE + " Then Lagos sent 900 builders.")
    gateway = ScriptedGateway(tellings=[invented] * 6)

    result = run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    assert result.published == []
    assert result.rejected[article.url_clean] == ["no telling passed the checks after one revision"]
    assert not Story.objects.exists()
    assert PipelineRun.objects.get(pk=result.run_id).status == PipelineRun.Status.FAILED


def test_an_article_is_told_only_once(article: Article) -> None:
    run_pipeline(limit=1, gateway=ScriptedGateway(), fetch=fetched)

    second = run_pipeline(limit=1, gateway=ScriptedGateway(), fetch=fetched)

    assert second.published == [] and second.rejected == {}
    assert Story.objects.count() == 1


def test_an_unreadable_article_falls_back_to_its_feed_snippet(article: Article) -> None:
    def refused(url: str) -> ArticleText:
        raise ArticleFetchError("robots.txt does not allow fetching this article.")

    gateway = ScriptedGateway()
    run_pipeline(limit=1, gateway=gateway, fetch=refused)

    evidence = gateway.calls[0][1]["evidence"]
    assert evidence["text"] == f"{article.title}\n{article.snippet}"
    assert StageTrace.objects.get(stage="read_article").status == StageTrace.Status.SKIPPED


def test_the_editor_model_sends_an_invented_detail_back_for_revision(article: Article) -> None:
    invented = TellingCheck(
        reasoning="One invented cause.",
        issues=[TellingIssue(quote="the river is no wall", problem="the facts give no flood")],
    )
    gateway = ScriptedGateway(reviews=[invented])  # first tone's first draft only

    result = run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    revision = gateway.calls[4][1]["revision"]  # facts, rerank, write, check, write again
    assert revision["problems"] == ['editor: "the river is no wall": the facts give no flood']
    telling = Story.objects.get(pk=result.published[0]).tellings.get(tone="light")
    assert telling.revision_count == 1
    assert telling.checker_report["editor"]["reasoning"] == "Faithful."


def test_a_telling_the_editor_cannot_check_is_not_published(article: Article) -> None:
    down = LLMProviderError("unavailable")
    gateway = ScriptedGateway(reviews=[down] * 6)

    result = run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    assert result.published == []
    assert not Story.objects.exists()


def test_the_writer_and_the_rules_may_use_the_context(article: Article) -> None:
    gateway = ScriptedGateway()

    run_pipeline(limit=1, gateway=gateway, fetch=fetched)

    writer = next(v for name, v in gateway.calls if name == "write_telling")
    assert writer["context"] == [{"kind": "background", "text": "SYNTHETIC: The river flooded."}]


def test_older_stories_get_context_and_perspectives_without_changing_their_facts(
    article: Article,
) -> None:
    run_pipeline(limit=1, gateway=ScriptedGateway(), fetch=fetched)
    story = Story.objects.get()
    story.context_items.all().delete()
    story.perspectives.all().delete()
    facts_before = list(story.facts.values_list("text", flat=True))

    outcome = add_missing_layers(gateway=ScriptedGateway(), fetch=fetched)

    assert outcome == {story.pk: "1 context, 1 perspectives"}
    assert story.context_items.count() == 1 and story.perspectives.count() == 1
    assert list(story.facts.values_list("text", flat=True)) == facts_before
    assert add_missing_layers(gateway=ScriptedGateway(), fetch=fetched) == {}  # done once


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("Students blocked hundreds of schools in late September.", True),
        ("The ministry says schools may reopen next week.", True),
        ("The statement suggests legal responses may follow.", False),
        ("The article does not specify what happens next.", False),
    ],
)
def test_context_that_guesses_is_dropped(text: str, kept: bool) -> None:
    facts = EstablishedFacts(
        reasoning="x",
        facts=FACTS,
        context=[ContextNote(kind="consequence", text=text)],
        themes=[],
        tone_class="neutral",
        tone_class_reason="x",
    )
    assert bool(facts.context) is kept
