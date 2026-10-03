"""Fetch a news article's words for the editorial pipeline, politely, without storing them.

The tale is only as rich as what the writer knows, and a feed's one-line summary is too
thin to tell a story from. So the pipeline reads the article itself. The text is held in
memory for fact extraction and never written to the database or spoken: Greeo stores
only the headline, link and a short snippet (rule 5), and the copy guard stops a tale
reusing the publisher's sentences.

Politeness rules: an honest User-Agent, robots.txt is obeyed, and 403/429 stop the
fetch instead of retrying.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from django.conf import settings

MAX_BYTES = 2_000_000
# Containers whose text is never the article: navigation, chrome, scripts, forms.
SKIP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "figure"}
BLOCK_TAGS = {"p", "h2", "h3", "li", "blockquote"}


class ArticleFetchError(Exception):
    """The article could not be read; the caller falls back to the feed snippet."""


@dataclass(frozen=True)
class ArticleText:
    url: str
    text: str
    words: int


def user_agent() -> str:
    return f"GreeoBot/0.1 (+{settings.GREEO_CONTACT_EMAIL})"


def fetch_article_text(url: str, client: httpx.Client | None = None) -> ArticleText:
    """Read one article's paragraphs, or raise ArticleFetchError with a plain reason."""
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    try:
        if not allowed_by_robots(url, client):
            raise ArticleFetchError("robots.txt does not allow fetching this article.")
        response = client.get(
            url,
            headers={"User-Agent": user_agent(), "Accept": "text/html"},
            timeout=settings.NEWS_HTTP_TIMEOUT_SECONDS,
        )
        if response.status_code in {403, 429}:
            raise ArticleFetchError(f"The publisher refused the request ({response.status_code}).")
        if response.status_code != 200:
            raise ArticleFetchError(f"The publisher answered {response.status_code}.")
        text = article_text(response.content[:MAX_BYTES].decode("utf-8", errors="replace"))
    except httpx.HTTPError as error:
        raise ArticleFetchError(f"The article could not be reached: {error}") from error
    finally:
        if owns_client:
            client.close()
    if not text:
        raise ArticleFetchError("No article paragraphs were found on the page.")
    return ArticleText(url=url, text=text, words=len(text.split()))


def allowed_by_robots(url: str, client: httpx.Client) -> bool:
    """True when robots.txt allows GreeoBot; a missing robots.txt allows everything."""
    parts = urlsplit(url)
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        response = client.get(
            robots_url,
            headers={"User-Agent": user_agent()},
            timeout=settings.NEWS_HTTP_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return False
    if response.status_code in {401, 403}:
        return False
    if response.status_code >= 400:
        return True
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser.can_fetch("GreeoBot", url)


def article_text(html: str) -> str:
    """The article's paragraphs as plain text, one per line.

    Paragraphs inside <article> win when the page has one; otherwise every paragraph
    outside navigation and page chrome is used.
    """
    parser = _ParagraphParser()
    parser.feed(html)
    parser.close()
    blocks = parser.in_article or parser.everywhere
    return "\n".join(blocks)


class _ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.article_depth = 0
        self.block: list[str] | None = None
        self.in_article: list[str] = []
        self.everywhere: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self.skip_depth += 1
        elif tag == "article":
            self.article_depth += 1
        elif tag in BLOCK_TAGS and not self.skip_depth:
            self.block = []

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "article" and self.article_depth:
            self.article_depth -= 1
        elif tag in BLOCK_TAGS and self.block is not None:
            text = re.sub(r"\s+", " ", "".join(self.block)).strip()
            if len(text.split()) >= 4:
                self.everywhere.append(text)
                if self.article_depth:
                    self.in_article.append(text)
            self.block = None

    def handle_data(self, data: str) -> None:
        if self.block is not None and not self.skip_depth:
            self.block.append(data)
