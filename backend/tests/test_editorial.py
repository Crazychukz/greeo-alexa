"""Article reading, proverb choice by meaning, trusting the corpus, and temperatures."""

from __future__ import annotations

from io import StringIO

import httpx
import pytest
from apps.llm.client import temperature_for_prompt
from apps.news.article import ArticleFetchError, article_text, fetch_article_text
from apps.stories.drafts import ProverbPick, ProverbRanking
from apps.wisdom.models import Proverb
from apps.wisdom.services import choose_proverbs
from django.core.management import call_command

from tests.factories import ProverbFactory

PAGE = """<html><head><script>var x = 'not this';</script></head><body>
<nav><p>Home News Sport Weather Menu</p></nav>
<article><h1>Headline</h1>
<p>The first paragraph of the story, with enough words.</p>
<figure><p>A caption that is not the story text.</p></figure>
<p>The second paragraph &amp; its ending.</p></article>
<footer><p>Copyright notice and terms of use here.</p></footer></body></html>"""


def client_for(pages: dict[str, tuple[int, str]]) -> httpx.Client:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        status, body = pages.get(str(request.url), (404, ""))
        return httpx.Response(status, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.seen_agents = seen  # type: ignore[attr-defined]
    return client


def test_article_text_keeps_story_paragraphs_and_drops_page_chrome() -> None:
    assert article_text(PAGE) == (
        "The first paragraph of the story, with enough words.\nThe second paragraph & its ending."
    )


def test_fetch_reads_the_article_politely() -> None:
    client = client_for({"https://news.test/a": (200, PAGE)})

    article = fetch_article_text("https://news.test/a", client=client)

    assert article.words == 15
    assert all(agent.startswith("GreeoBot/") for agent in client.seen_agents)


@pytest.mark.parametrize(
    ("pages", "reason"),
    [
        ({"https://news.test/robots.txt": (200, "User-agent: *\nDisallow: /")}, "robots.txt"),
        ({"https://news.test/a": (403, "")}, "refused"),
        ({"https://news.test/a": (429, "")}, "refused"),
        ({"https://news.test/a": (200, "<p>too short</p>")}, "No article paragraphs"),
    ],
)
def test_fetch_stops_on_robots_refusals_and_empty_pages(pages, reason) -> None:
    with pytest.raises(ArticleFetchError, match=reason):
        fetch_article_text("https://news.test/a", client=client_for(pages))


class RankingGateway:
    def __init__(self, ranking: ProverbRanking) -> None:
        self.ranking = ranking
        self.variables: dict = {}

    def generate_json(self, prompt_name, variables, output_model):
        assert prompt_name == "rerank_proverb" and output_model is ProverbRanking
        self.variables = variables
        return self.ranking


@pytest.mark.django_db
def test_proverbs_are_chosen_by_meaning_from_the_whole_servable_corpus() -> None:
    fits = ProverbFactory(themes=[], meaning_note="Adapt when conditions change.")
    also = ProverbFactory(themes=[])
    ProverbFactory(tone_ok=False)  # not servable, never offered
    gateway = RankingGateway(
        ProverbRanking(
            reasoning="It is about adapting.",
            best=ProverbPick(id=fits.id, why="adaptation"),
            alternates=[ProverbPick(id="pv_invented", why="x"), ProverbPick(id=also.id, why="y")],
        )
    )

    chosen, reasoning = choose_proverbs([{"id": "F1", "text": "x"}], "neutral", gateway)

    assert [c.proverb for c in chosen] == [fits, also]
    assert reasoning == "It is about adapting."
    offered = {p["id"]: p for p in gateway.variables["proverbs"]}
    assert set(offered) == {fits.id, also.id}
    assert offered[fits.id]["meaning"] == "Adapt when conditions change."


@pytest.mark.django_db
def test_sensitive_stories_get_no_proverbs_and_no_model_call() -> None:
    ProverbFactory()

    chosen, reasoning = choose_proverbs([], "sensitive", gateway=object())

    assert chosen == [] and "Sensitive" in reasoning


@pytest.mark.django_db
def test_trusting_the_corpus_approves_every_proverb_and_can_be_undone(settings) -> None:
    settings.DEMO_ALLOW_SINGLE_SOURCE_PROVERBS = True
    ProverbFactory(tone_ok=False, verification_status=Proverb.VerificationStatus.SINGLE_SOURCE)
    ProverbFactory(tone_ok=False)

    out = StringIO()
    call_command("trust_proverbs", stdout=out)
    assert Proverb.objects.servable().count() == 2
    assert "Approved 2 proverbs" in out.getvalue()

    call_command("trust_proverbs", "--undo", stdout=StringIO())
    assert Proverb.objects.servable().count() == 0


def test_only_the_writer_gets_a_warmer_temperature(monkeypatch) -> None:
    assert temperature_for_prompt("write_telling") == 0.6
    assert temperature_for_prompt("establish_facts") == 0.0
    monkeypatch.setenv("LLM_ESTABLISH_FACTS_TEMPERATURE", "0.2")
    assert temperature_for_prompt("establish_facts") == 0.2
