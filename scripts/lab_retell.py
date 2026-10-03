"""Lab: retell a live headline with the configured model and keep everything.

An investigation tool, not product code. It runs the editorial steps on one article:

  1. read      the article's own words (robots.txt obeyed), falling back to the feed summary
  2. facts     establish_facts: facts, themes and tone class, with reasoning
  3. proverbs  rerank_proverb: chosen by meaning from the whole servable corpus
  4. tell      write_telling: one whole tale per allowed tone, proverbs woven in as slots
  5. beats     code splits the tale into 3-5 beats; product validators run; slots filled

Every prompt sent and every raw reply is saved under lab/runs/<timestamp>-<slug>/, with
report.md to read first. Nothing is written to the database. The article text appears
only in the prompt files, which stay local (lab/ is gitignored).

Run with `make lab` (ITEM=1 for the next headline, FEED=<rss url> for another feed).
Needs LLM_BACKEND=bedrock.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, "/app/backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

import httpx  # noqa: E402
from django.conf import settings  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from apps.llm.backends import without_reasoning  # noqa: E402
from apps.llm.client import (  # noqa: E402
    configured_backend,
    model_for_prompt,
    render_prompt,
    render_repair_prompt,
    temperature_for_prompt,
)
from apps.llm.prompt_registry import load_prompt  # noqa: E402
from apps.news.article import ArticleFetchError, fetch_article_text  # noqa: E402
from apps.stories import validators  # noqa: E402
from apps.stories.composition import TellingDraft, split_tale, used_slots  # noqa: E402
from apps.stories.drafts import EstablishedFacts, ProverbRanking  # noqa: E402
from apps.stories.voices import voice_for  # noqa: E402
from apps.wisdom.models import Proverb  # noqa: E402
from apps.wisdom.rendering import fill_slots  # noqa: E402
from apps.wisdom.services import proverb_for_prompt  # noqa: E402
from apps.wisdom.themes import theme_vocabulary  # noqa: E402

DEFAULT_FEED = "https://feeds.bbci.co.uk/news/world/africa/rss.xml"
OUT_ROOT = Path("/app/lab/runs")
MAX_TOKENS = 3000
TONES = ("light", "balanced", "serious")
TARGET_WORDS = 250
MAX_WORDS = 320  # five beats of about 65 words
ARTICLE_CHARS = 12000


def top_item(feed_url: str, index: int) -> dict[str, str]:
    """The index-th item from the feed published in the last 48 hours."""
    response = httpx.get(
        feed_url, timeout=20, follow_redirects=True, headers={"User-Agent": "GreeoBot/0.1 lab"}
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    channel = root.find("channel")
    publisher = (channel.findtext("title") if channel is not None else "") or feed_url
    cutoff = datetime.now(UTC) - timedelta(hours=48)
    recent = []
    for item in root.iter("item"):
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if when >= cutoff:
            recent.append(
                {
                    "publisher": publisher.strip(),
                    "headline": (item.findtext("title") or "").strip(),
                    "summary": re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip(),
                    "url": (item.findtext("link") or "").strip(),
                    "published": when.isoformat(),
                }
            )
    if len(recent) <= index:
        raise SystemExit(f"Only {len(recent)} items from the last 48 hours in {feed_url}.")
    return recent[index]


class Recorder:
    """Calls the model with a registered prompt; saves each prompt and raw reply."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.backend = configured_backend()
        self.calls: list[dict[str, Any]] = []

    def ask[M: BaseModel](self, step: str, prompt_name: str, variables: dict, model: type[M]) -> M:
        """One call, and one repair attempt on invalid JSON, as the product gateway does."""
        prompt = render_prompt(load_prompt(prompt_name), variables, model)
        text = self._call(step, prompt, prompt_name)
        try:
            return model.model_validate_json(json_object(text))
        except ValueError:
            repair = render_repair_prompt(prompt, text, model)
            text = self._call(f"{step}.repair", repair, prompt_name)
            return model.model_validate_json(json_object(text))

    def _call(self, step: str, prompt: str, prompt_name: str) -> str:
        model_id = model_for_prompt(prompt_name)
        temperature = temperature_for_prompt(prompt_name)
        (self.folder / f"{step}.prompt.txt").write_text(prompt)
        started = time.monotonic()
        response = self.backend.generate(
            prompt=prompt, model_id=model_id, max_tokens=MAX_TOKENS, temperature=temperature
        )
        (self.folder / f"{step}.raw.txt").write_text(response.text)
        self.calls.append(
            {
                "step": step,
                "model": model_id,
                "temperature": temperature,
                "ms": round((time.monotonic() - started) * 1000),
                "tokens_in": response.tokens_in,
                "tokens_out": response.tokens_out,
            }
        )
        return response.text


def json_object(raw: str) -> str:
    """The JSON object in a reply, ignoring reasoning blocks and code fences."""
    text = without_reasoning(raw)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object in reply: {raw[:300]!r}")
    return text[start : end + 1]


MONTHS = (
    "January February March April May June July August September October November December"
).split()


def readable_dates(text: str) -> list[str]:
    """Each ISO date in the text written out, as a tale would say it."""
    return [
        f"{int(day)} {MONTHS[int(month) - 1]} {year}"
        for year, month, day in re.findall(r"(\d{4})-(\d{2})-(\d{2})", text)
        if 1 <= int(month) <= 12
    ]


def check_telling(
    draft: TellingDraft, offered: dict, sources: list[str], body: str, tone_class: str
) -> dict[str, Any]:
    """Split into beats, run the product checks, and fill the proverb slots."""
    spoken_by_slot, problems = used_slots(
        draft, {slot: p.spoken_form for slot, p in offered.items()}
    )
    beats, split_problems = split_tale(draft.tale, spoken_by_slot)
    problems += split_problems
    problems += validators.check_beats(beats, spoken_by_slot)
    problems += validators.check_proverb_copies(draft.tale, spoken_by_slot)
    problems += validators.check_closing(
        draft.closing_kind, draft.closing_text, sources, tone_class
    )
    rendered = []
    for number, beat in enumerate(beats, start=1):
        try:
            text = fill_slots(beat, spoken_by_slot)
        except Exception as error:  # an unknown slot: keep the template so it can be read
            text = beat
            problems.append(f"beat {number}: {error}")
        rendered.append(text)
        problems += [f"beat {number}: {p}" for p in validators.check_faithfulness(beat, sources)]
        problems += [f"beat {number}: {p}" for p in validators.check_copy(text, [body])]
        problems += [f"beat {number}: {p}" for p in validators.check_voice_vocabulary(text)]
    return {
        "tale_template": draft.tale,
        "beats": beats,
        "rendered": rendered,
        "words": sum(len(b.split()) for b in rendered),
        "proverbs_used": sorted(spoken_by_slot),
        "closing_kind": draft.closing_kind,
        "closing_text": draft.closing_text,
        "problems": list(dict.fromkeys(problems)),
    }


def run(feed: str, index: int) -> Path:
    item = top_item(feed, index)
    slug = re.sub(r"[^a-z0-9]+", "-", item["headline"].lower()).strip("-")[:50]
    folder = OUT_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    folder.mkdir(parents=True)
    rec = Recorder(folder)

    # 1. Read the article itself
    try:
        article = fetch_article_text(item["url"])
        body, article_words, article_note = article.text[:ARTICLE_CHARS], article.words, ""
    except ArticleFetchError as error:
        body, article_words, article_note = item["summary"], 0, str(error)

    # 2. Facts
    facts = rec.ask(
        "1-facts",
        "establish_facts",
        {
            "evidence": {
                "publisher": item["publisher"],
                "date": item["published"][:10],
                "headline": item["headline"],
                "text": body,
            },
            "theme_vocabulary": theme_vocabulary(),
        },
        EstablishedFacts,
    )
    fact_list = [fact.model_dump() for fact in facts.facts]

    # 3. Proverbs, by meaning, from the whole servable corpus
    pool = {p.id: p for p in Proverb.objects.servable()}
    ranking: ProverbRanking | None = None
    chosen: list[tuple[Proverb, str]] = []
    if facts.tone_class != "sensitive" and pool:
        ranking = rec.ask(
            "2-proverbs",
            "rerank_proverb",
            {"facts": fact_list, "proverbs": [proverb_for_prompt(p) for p in pool.values()]},
            ProverbRanking,
        )
        picks = [ranking.best, *ranking.alternates] if ranking.best else ranking.alternates
        seen: set[str] = set()
        for pick in picks:
            if pick and pick.id in pool and pick.id not in seen:
                seen.add(pick.id)
                chosen.append((pool[pick.id], pick.why))
        chosen = chosen[:3]
    offered = {f"P{n}": proverb for n, (proverb, _) in enumerate(chosen, start=1)}

    # 4 and 5. Tell each allowed tone, split into beats, check, render
    tones = [t for t in TONES if not (t == "light" and facts.tone_class == "sensitive")]
    # The writer may name only what the facts, the title and the offered proverbs' peoples name.
    sources = [
        *(fact.text for fact in facts.facts),
        item["headline"],
        *(p.culture for p in offered.values()),
        # Facts may write dates as 2026-10-01; a tale says 1 October 2026.
        *readable_dates(" ".join(fact.text for fact in facts.facts) + " " + item["published"]),
    ]
    tellings = {}
    for tone in tones:
        voice = voice_for(tone, facts.tone_class)
        variables = {
            "facts": fact_list,
            "context": [],
            "tone": tone,
            "tone_class": facts.tone_class,
            "voice": {"name": voice.name, "style": voice.style},
            "proverbs": {
                slot: {"text": p.spoken_form, "meaning": p.meaning_note, "culture": p.culture}
                for slot, p in offered.items()
            },
            "target_words": TARGET_WORDS,
            "max_words": MAX_WORDS,
        }
        draft = rec.ask(f"3-tell-{tone}", "write_telling", variables, TellingDraft)
        telling = check_telling(draft, offered, sources, body, facts.tone_class)
        first_problems = telling["problems"]
        if first_problems:
            # One bounded revision, as the pipeline will do: fix exactly what was found.
            revision = {
                "tale": draft.tale,
                "closing_text": draft.closing_text,
                "problems": first_problems,
            }
            draft = rec.ask(
                f"4-revise-{tone}",
                "write_telling",
                {**variables, "revision": revision},
                TellingDraft,
            )
            telling = check_telling(draft, offered, sources, body, facts.tone_class)
        tellings[tone] = {
            "voice": voice.name,
            **telling,
            "revised": bool(first_problems),
            "first_draft_problems": first_problems,
        }

    result = {
        "feed": feed,
        "item": item,
        "article_words": article_words,
        "article_note": article_note,
        "backend": settings.LLM_BACKEND,
        "facts": facts.model_dump(),
        "proverb_pool_size": len(pool),
        "proverb_reasoning": ranking.reasoning if ranking else "",
        "proverbs_offered": {
            slot: {
                "id": p.id,
                "text": p.spoken_form,
                "meaning": p.meaning_note,
                "culture": p.culture,
                "source_citation": p.source_citation,
                "verification_status": p.verification_status,
                "why": why,
            }
            for (slot, p), (_, why) in zip(offered.items(), chosen, strict=True)
        },
        "tellings": tellings,
        "calls": rec.calls,
    }
    (folder / "run.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    (folder / "report.md").write_text(report(result))
    return folder


def report(r: dict[str, Any]) -> str:
    item, f = r["item"], r["facts"]
    calls = ", ".join(f"{c['step']} {c['ms']} ms (t={c['temperature']})" for c in r["calls"])
    read = (
        f"{r['article_words']} words of the article"
        if r["article_words"]
        else f"feed summary only ({r['article_note']})"
    )
    lines = [
        f"# Lab retelling: {item['headline']}",
        "",
        f"- Published {item['published'][:16]} by {item['publisher']}: {item['url']}",
        f"- Read: {read}",
        f"- Model: `{r['calls'][0]['model']}` via {r['backend']}. Calls: {calls}",
        "",
        "Lab output: not reviewed, not for publication.",
        "",
        "## Facts",
        "",
        f"*Reasoning:* {f['reasoning']}",
        "",
        *[f"- {x['id']}: {x['text']}" for x in f["facts"]],
        "",
        f"Themes: {', '.join(f['themes'])}. Tone class: **{f['tone_class']}**. "
        f"{f['tone_class_reason']}",
        "",
        "## Proverbs",
        "",
    ]
    if not r["proverbs_offered"]:
        lines += ["None: sensitive stories get no proverbs.", ""]
    else:
        lines += [
            f"Chosen by meaning from {r['proverb_pool_size']} proverbs.",
            "",
            f"*Reasoning:* {r['proverb_reasoning']}",
            "",
        ]
        for slot, p in r["proverbs_offered"].items():
            lines += [
                f"- **{slot}** ({p['culture']}): {p['text']}",
                f"  - Meaning: {p['meaning']}",
                f"  - Why: {p['why']}",
            ]
        lines += [""]
    lines += ["## Tellings", ""]
    for tone, t in r["tellings"].items():
        used = ", ".join(t["proverbs_used"]) or "none"
        lines += [f"### {tone.title()}, {t['voice']} ({t['words']} words, proverbs: {used})", ""]
        if t["revised"]:
            lines += [
                "*Revised once. The first draft had:* "
                + "; ".join(t["first_draft_problems"]),
                "",
            ]
        for number, beat in enumerate(t["rendered"], start=1):
            lines += [f"**{number}.** {beat}", ""]
        lines += [f"*Closing ({t['closing_kind']}):* {t['closing_text'] or '(none)'}", ""]
        if t["problems"]:
            lines += ["Check findings:", "", *[f"- {p}" for p in t["problems"]], ""]
        else:
            lines += ["Checks: no findings.", ""]
    lines += [
        "## Files",
        "",
        "`*.prompt.txt` is exactly what was sent (including the article text);",
        "`*.raw.txt` is exactly what came back; `run.json` has everything.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if settings.LLM_BACKEND != "bedrock":
        raise SystemExit("Set LLM_BACKEND=bedrock in .env; the mock model has nothing to show.")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--feed", default=os.environ.get("FEED") or DEFAULT_FEED)
    parser.add_argument("--item", type=int, default=int(os.environ.get("ITEM") or 0))
    args = parser.parse_args()
    out = run(args.feed, args.item)
    print(f"Saved: lab/runs/{out.name}/report.md")
