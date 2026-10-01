"""Lab: retell today's top headline with the configured model and keep everything.

An investigation tool, not product code. It fetches one public RSS feed (headline and
summary only), then runs the steps the editorial pipeline will run:

  1. analyse   facts, themes and tone class from the evidence (lab prompt, with reasoning)
  2. proverbs  rules-first candidates from the corpus, then a model pick (lab prompt)
  3. tell      the registered write_telling prompt, once per allowed tone
  4. render    proverb slots filled with verified spoken forms; product validators run

Every prompt sent and every raw reply (including any <thinking> the model writes) is
saved under lab/runs/<timestamp>-<slug>/, with report.md to read first. Nothing is
written to the database. Steps 1 and 2 use lab prompts because the registered ones are
still stubs; they are labelled LAB in the output.

Run with `make lab` (or FEED=<rss url> make lab). Needs LLM_BACKEND=bedrock.
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
from typing import Any, Literal

sys.path.insert(0, "/app/backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402

django.setup()

import httpx  # noqa: E402
from django.conf import settings  # noqa: E402
from pydantic import BaseModel, field_validator  # noqa: E402

from apps.llm.backends import without_reasoning  # noqa: E402
from apps.llm.client import configured_backend, model_for_prompt, render_prompt  # noqa: E402
from apps.llm.prompt_registry import load_prompt  # noqa: E402
from apps.stories import validators  # noqa: E402
from apps.stories.voices import ROLE_GUIDANCE, beat_roles, voice_for  # noqa: E402
from apps.wisdom.rendering import fill_slots  # noqa: E402
from apps.wisdom.models import Proverb  # noqa: E402
from apps.wisdom.services import candidates_for_story  # noqa: E402
from apps.wisdom.themes import theme_vocabulary  # noqa: E402

DEFAULT_FEED = "https://feeds.bbci.co.uk/news/world/africa/rss.xml"
OUT_ROOT = Path("/app/lab/runs")
MAX_TOKENS = 2000
TONES = ("light", "balanced", "serious")


# Output shapes ---------------------------------------------------------------------------


class Fact(BaseModel):
    id: str
    text: str


class Analysis(BaseModel):
    reasoning: str
    facts: list[Fact]

    @field_validator("facts", mode="before")
    @classmethod
    def number_plain_strings(cls, value: Any) -> Any:
        """Accept facts given as plain strings; recorded in the raw reply either way."""
        if isinstance(value, list):
            return [{"id": f"F{n}", "text": v} if isinstance(v, str) else v
                    for n, v in enumerate(value, start=1)]  # fmt: skip
        return value

    themes: list[str]
    tone_class: Literal["neutral", "sensitive"]
    tone_class_reason: str


class Pick(BaseModel):
    candidate_id: str
    role: Literal["opening", "turn", "closing"]
    why: str


class ProverbChoice(BaseModel):
    reasoning: str
    picks: list[Pick]


class Telling(BaseModel):
    beats: list[str]
    closing_kind: Literal["moral", "reflection", "none"]
    closing_text: str


# Lab prompts (the registered analyse and rerank prompts are stubs) ------------------------

ANALYSE = """LAB PROMPT: analyse one news item for a spoken storytelling product.

You receive one piece of evidence, E1: a headline and a short summary from a publisher.

Return a JSON object with:
- reasoning: a few sentences on what the item says, what it does not say, and how sure
  you can be. This is for the editor, not the listener.
- facts: 2 to 6 objects {{"id": "F1", "text": "..."}}, each a short atomic statement
  fully supported by E1 alone. No inference, no background knowledge, no numbers or
  names that E1 does not contain.
- themes: 1 to 4 keys from THEME_VOCABULARY that the facts support.
- tone_class: "sensitive" for death, violence, disaster, abuse, illness, conflict,
  or anything where a light treatment would be disrespectful; otherwise "neutral".
- tone_class_reason: one sentence.

Return only the JSON object.

THEME_VOCABULARY:
{themes}

E1:
{evidence}
"""

CHOOSE = """LAB PROMPT: choose proverbs for a spoken telling of a news event.

You receive the established facts and up to eight candidate proverbs from a verified
corpus. Choose at most two that genuinely fit the human situation in the facts. Choosing
none is better than a forced fit. A proverb must never seem to judge a real person or
take a side in a dispute.

Roles: "opening" frames the situation; "turn" marks the moment things change;
"closing" sums up. Use each role at most once.

Return a JSON object with:
- reasoning: a few sentences on how you weighed the candidates, including any you
  rejected and why.
- picks: [{{"candidate_id", "role", "why"}}], at most two.

Return only the JSON object.

FACTS:
{facts}

CANDIDATES:
{candidates}
"""

ROLE_FOR_SLOT = {
    "opening": "frames the situation, near the start",
    "turn": "marks the moment things change",
    "closing": "sums up, near the end",
}


# Steps -----------------------------------------------------------------------------------


def top_item(feed_url: str, index: int) -> dict[str, str]:
    """The index-th item from the feed published in the last 48 hours."""
    response = httpx.get(
        feed_url, timeout=20, follow_redirects=True, headers={"User-Agent": "greeo-lab/0.1"}
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    channel = root.find("channel")
    publisher = (channel.findtext("title") if channel is not None else "") or feed_url
    cutoff = datetime.now(UTC) - timedelta(hours=48)
    recent = []
    for item in root.iter("item"):
        published = item.findtext("pubDate") or ""
        try:
            when = parsedate_to_datetime(published)
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
    """Calls the model and saves each prompt and raw reply next to the report."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.backend = configured_backend()
        self.calls: list[dict[str, Any]] = []

    def ask[M: BaseModel](self, step: str, prompt: str, model: type[M], prompt_name: str) -> M:
        model_id = model_for_prompt(prompt_name)
        (self.folder / f"{step}.prompt.txt").write_text(prompt)
        started = time.monotonic()
        response = self.backend.generate(prompt=prompt, model_id=model_id, max_tokens=MAX_TOKENS)
        ms = round((time.monotonic() - started) * 1000)
        (self.folder / f"{step}.raw.txt").write_text(response.text)
        self.calls.append(
            {"step": step, "model": model_id, "ms": ms,
             "tokens_in": response.tokens_in, "tokens_out": response.tokens_out}
        )  # fmt: skip
        return model.model_validate_json(json_object(response.text))


def json_object(raw: str) -> str:
    """The JSON object in a reply, ignoring reasoning blocks and code fences."""
    text = without_reasoning(raw)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object in reply: {raw[:300]!r}")
    return text[start : end + 1]


def reasoning_in(raw: str) -> str:
    found = re.findall(r"<thinking>(.*?)(?:</thinking>|\Z)", raw, re.DOTALL | re.IGNORECASE)
    return "\n".join(part.strip() for part in found)


def unreviewed_candidates(themes: list[str], tone_class: str, limit: int = 8) -> list[Proverb]:
    """LAB ONLY: also offer imported proverbs nobody has approved yet (tone_ok false).

    The product never does this. It lets you see how the model handles real proverbs
    before the corpus review is done. The sensitive-story rule still applies.
    """
    if tone_class == "sensitive":
        return []
    wanted = set(themes)
    pool = [p for p in Proverb.objects.exclude(themes=[]) if wanted & set(p.themes)]
    pool.sort(key=lambda p: (-len(wanted & set(p.themes)), p.id))
    return pool[:limit]


def run(feed: str, index: int, beats: int, unreviewed: bool = False) -> Path:
    item = top_item(feed, index)
    slug = re.sub(r"[^a-z0-9]+", "-", item["headline"].lower()).strip("-")[:50]
    folder = OUT_ROOT / f"{datetime.now():%Y%m%d-%H%M%S}-{slug}"
    folder.mkdir(parents=True)
    rec = Recorder(folder)
    evidence = f"{item['publisher']}, {item['published'][:10]}\n{item['headline']}\n{item['summary']}"

    # 1. Analyse
    vocabulary = theme_vocabulary()
    analysis = rec.ask(
        "1-analyse",
        ANALYSE.format(
            themes="\n".join(f"- {key}: {text}" for key, text in vocabulary.items()),
            evidence=evidence,
        ),
        Analysis,
        "establish_facts",
    )
    unknown_themes = [theme for theme in analysis.themes if theme not in vocabulary]
    themes = [theme for theme in analysis.themes if theme in vocabulary]

    # 2. Proverbs: rules first (the product refuses all proverbs on sensitive stories)
    candidates = (
        unreviewed_candidates(themes, analysis.tone_class)
        if unreviewed
        else candidates_for_story(themes, analysis.tone_class, limit=8)
    )
    choice: ProverbChoice | None = None
    picked = []
    if candidates:
        choice = rec.ask(
            "2-proverbs",
            CHOOSE.format(
                facts="\n".join(f"{fact.id}: {fact.text}" for fact in analysis.facts),
                candidates="\n".join(
                    json.dumps({"candidate_id": p.id, "proverb": p.spoken_form,
                                "meaning": p.meaning_note, "culture": p.culture,
                                "themes": p.themes})  # fmt: skip
                    for p in candidates
                ),
            ),
            ProverbChoice,
            "rerank_proverb",
        )
        by_id = {p.id: p for p in candidates}
        roles_used: set[str] = set()
        for pick in choice.picks[:2]:
            if pick.candidate_id in by_id and pick.role not in roles_used:
                roles_used.add(pick.role)
                picked.append((pick, by_id[pick.candidate_id]))
    slots = {f"P{n}": (pick, proverb) for n, (pick, proverb) in enumerate(picked, start=1)}
    spoken_by_slot = {slot: proverb.spoken_form for slot, (_, proverb) in slots.items()}

    # 3 and 4. Tell in each allowed tone, render, validate
    tones = [t for t in TONES if not (t == "light" and analysis.tone_class == "sensitive")]
    roles = beat_roles(beats)
    fact_texts = [fact.text for fact in analysis.facts]
    # As in the product: the writer may only state the facts and the event title.
    sources = [*fact_texts, item["headline"]]
    tellings = {}
    definition = load_prompt("write_telling")
    for tone in tones:
        voice = voice_for(tone, analysis.tone_class)
        variables = {
            "pipeline_run_id": f"lab-{slug}",
            "facts": [fact.model_dump() for fact in analysis.facts],
            "context": [],
            "tone": tone,
            "tone_class": analysis.tone_class,
            "voice": {"name": voice.name, "style": voice.style},
            "beat_roles": [{"role": r, "guidance": ROLE_GUIDANCE[r]} for r in roles],
            "proverb_slots": {
                slot: {"role": pick.role, "placement": ROLE_FOR_SLOT[pick.role]}
                for slot, (pick, _) in slots.items()
            },
        }
        telling = rec.ask(
            f"3-tell-{tone}",
            render_prompt(definition, variables, Telling),
            Telling,
            "write_telling",
        )
        problems = validators.check_beats(telling.beats, spoken_by_slot)
        for n, beat in enumerate(telling.beats, start=1):
            rendered = fill_slots(beat, spoken_by_slot) if not problems else beat
            problems += [f"beat {n}: {p}" for p in validators.check_faithfulness(beat, sources)]
            problems += [f"beat {n}: {p}" for p in validators.check_copy(rendered, [item["summary"]])]
            problems += [f"beat {n}: {p}" for p in validators.check_voice_vocabulary(rendered)]
        problems += validators.check_closing(
            telling.closing_kind, telling.closing_text, sources, analysis.tone_class
        )
        try:
            rendered_beats = [fill_slots(beat, spoken_by_slot) for beat in telling.beats]
        except Exception as error:  # an unknown slot: keep the template so it can be read
            rendered_beats = telling.beats
            problems.append(f"render: {error}")
        tellings[tone] = {
            "voice": voice.name,
            "templates": telling.beats,
            "rendered": rendered_beats,
            "closing_kind": telling.closing_kind,
            "closing_text": telling.closing_text,
            "problems": problems,
            "thinking": reasoning_in((folder / f"3-tell-{tone}.raw.txt").read_text()),
        }

    result = {
        "feed": feed,
        "item": item,
        "model": rec.calls[0]["model"] if rec.calls else None,
        "backend": settings.LLM_BACKEND,
        "analysis": analysis.model_dump(),
        "analysis_thinking": reasoning_in((folder / "1-analyse.raw.txt").read_text()),
        "unknown_themes_dropped": unknown_themes,
        "unreviewed_proverbs_offered": unreviewed,
        "proverb_candidates": [
            {"id": p.id, "spoken_form": p.spoken_form, "culture": p.culture,
             "themes": p.themes, "verification_status": p.verification_status}  # fmt: skip
            for p in candidates
        ],
        "proverb_choice": choice.model_dump() if choice else None,
        "proverb_thinking": reasoning_in((folder / "2-proverbs.raw.txt").read_text())
        if choice
        else "",
        "slots": {
            slot: {"role": pick.role, "why": pick.why, "proverb_id": p.id,
                   "spoken_form": p.spoken_form, "culture": p.culture,
                   "source_citation": p.source_citation,
                   "verification_status": p.verification_status}  # fmt: skip
            for slot, (pick, p) in slots.items()
        },
        "tellings": tellings,
        "calls": rec.calls,
    }
    (folder / "run.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    (folder / "report.md").write_text(report(result))
    return folder


def report(r: dict[str, Any]) -> str:
    item, a = r["item"], r["analysis"]
    lines = [
        f"# Lab retelling: {item['headline']}",
        "",
        f"- Feed: {r['feed']}",
        f"- Published: {item['published']} by {item['publisher']}",
        f"- Link (for you, never spoken): {item['url']}",
        f"- Model: `{r['model']}` via {r['backend']}",
        f"- Calls: " + ", ".join(f"{c['step']} {c['ms']} ms, {c['tokens_in']}+{c['tokens_out']} tokens" for c in r["calls"]),
        "",
        "Lab tool output. Not product content, not reviewed, not for publication.",
        "",
        "## Evidence (E1)",
        "",
        f"> {item['headline']}",
        ">",
        f"> {item['summary']}",
        "",
        "## 1. Analysis (lab prompt)",
        "",
        f"**Model reasoning (asked for):** {a['reasoning']}",
        "",
    ]
    if r["analysis_thinking"]:
        lines += ["**Unprompted `<thinking>`:**", "", "```text", r["analysis_thinking"], "```", ""]
    lines += [f"- {f['id']}: {f['text']}" for f in a["facts"]]
    lines += [
        "",
        f"Themes: {', '.join(a['themes']) or 'none'}"
        + (f" (dropped, not in vocabulary: {', '.join(r['unknown_themes_dropped'])})" if r["unknown_themes_dropped"] else ""),
        "",
        f"Tone class: **{a['tone_class']}**. {a['tone_class_reason']}",
        "",
        "## 2. Proverbs",
        "",
    ]
    if not r["proverb_candidates"]:
        lines += ["No candidates: the product never puts proverbs on sensitive stories.", ""]
    else:
        if r["unreviewed_proverbs_offered"]:
            lines += ["**LAB ONLY: unapproved proverbs were offered (`--unreviewed-proverbs`).** "
                      "The product would not use these until a person approves them.", ""]  # fmt: skip
        lines += ["Rules-first candidates (theme overlap, then id):", ""]
        lines += [
            f"- `{p['id']}` {p['spoken_form']} ({p['culture']}; {', '.join(p['themes'])}; {p['verification_status']})"
            for p in r["proverb_candidates"]
        ]
        choice = r["proverb_choice"]
        lines += ["", f"**Model reasoning:** {choice['reasoning']}", ""]
        if r["proverb_thinking"]:
            lines += ["**Unprompted `<thinking>`:**", "", "```text", r["proverb_thinking"], "```", ""]
        if r["slots"]:
            lines += [f"- {slot} ({s['role']}): {s['spoken_form']} ({s['culture']}). Why: {s['why']}" for slot, s in r["slots"].items()]
        else:
            lines += ["The model chose none."]
        lines += [""]
    lines += ["## 3. Tellings", ""]
    for tone, t in r["tellings"].items():
        lines += [f"### {tone.title()}, {t['voice']}", ""]
        for n, (template, rendered) in enumerate(zip(t["templates"], t["rendered"]), start=1):
            lines += [f"**Beat {n}.** {rendered}", ""]
            if template != rendered:
                lines += [f"<sub>Template: {template}</sub>", ""]
        lines += [f"**Closing ({t['closing_kind']}).** {t['closing_text'] or '(none)'}", ""]
        if t["thinking"]:
            lines += ["**Unprompted `<thinking>`:**", "", "```text", t["thinking"], "```", ""]
        if t["problems"]:
            lines += ["Validator findings:", ""] + [f"- {p}" for p in t["problems"]] + [""]
        else:
            lines += ["Validators: no findings.", ""]
    lines += [
        "## Files",
        "",
        "`*.prompt.txt` is exactly what was sent; `*.raw.txt` is exactly what came back.",
        "`run.json` has everything in one place.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if settings.LLM_BACKEND != "bedrock":
        raise SystemExit("Set LLM_BACKEND=bedrock in .env; the mock model has nothing to show.")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--feed", default=os.environ.get("FEED") or DEFAULT_FEED)
    parser.add_argument("--item", type=int, default=int(os.environ.get("ITEM") or 0),
                        help="0 for the top story, 1 for the next, ...")  # fmt: skip
    parser.add_argument("--beats", type=int, default=4, choices=(3, 4, 5))
    parser.add_argument("--unreviewed-proverbs", action="store_true",
                        default=os.environ.get("UNREVIEWED") == "1",
                        help="LAB ONLY: also offer proverbs nobody has approved yet")  # fmt: skip
    args = parser.parse_args()
    out = run(args.feed, args.item, args.beats, args.unreviewed_proverbs)
    print(f"Saved: lab/runs/{out.name}/report.md")
