# Curated event guide

This guide explains how to write `data/demo_event.yaml`: one real news event, the
evidence behind it, and the tellings Greeo speaks. The file is the golden fixture for
the demo, so you write every word of it; the loader only checks and stores it.

Start from `data/demo_event.template.yaml`. The loader refuses any file that still
contains the word `TODO`. Compare with `data/demo_event.synthetic.yaml`, a complete,
fictional example that passes every check.

## Load it

```sh
make demo                                   # loads data/demo_event.yaml (reloads with --replace)
docker compose exec web python manage.py load_demo_event ../data/demo_event.yaml
```

If anything is wrong, nothing is written and every problem is listed at once, each
with its location, for example `tellings.balanced.beats[2]: mentions the number 450,
which is not in the facts.` Loading the same event again needs `--replace`; the story
keeps its id, so listeners' memory of it survives.

## Schema

| Section | Fields | Rules |
| --- | --- | --- |
| `event` | `title`, `region`, `occurred_on`, `tone_class`, `themes` | Title at most 120 characters. `tone_class` is `neutral` or `sensitive`. Themes must be keys in `data/themes.yaml`. |
| `evidence[]` | `key`, `publisher`, `headline`, `url`, `published_on`, `note`, optional `language` | `key` uses lowercase letters, digits, `-` and `_`, and is unique. `note` is at most 300 characters. |
| `facts[]` | `text`, `evidence[]` | At least two facts. Each cites at least one evidence key. |
| `context[]` | `kind`, `text`, `evidence[]` | Optional. `kind` is `background`, `why_it_matters` or `consequence`. |
| `perspectives[]` | `label`, `summary`, `evidence[]` | Optional. Stored only if all perspectives together cite two or more publishers. |
| `proverbs` | slot (`P1`, `P2`, ...) to `{id, role}` | Optional. `id` is an existing verified, tone-approved proverb. `role` is `opening`, `turn` or `closing`. |
| `tellings` | `balanced` (required), `light`, `serious` | Each has `beats[]`, `closing_kind` and `closing_text`. |

Unknown keys are errors, so a typo such as `regoin` is caught rather than ignored.

## Evidence notes: your own words

A note says what the source reports, in your words, in at most 300 characters. Do not
paste sentences from the article.

Why: Greeo stores only a headline, a clean link and a short note, never article text.
That respects publishers' terms and keeps the demo honest about what it relies on. The
loader enforces it: a beat or closing that shares 15 or more consecutive words with any
note is rejected. Paraphrasing the note carefully also protects you, because the notes
are published with the story as its sources.

Links lose tracking parameters (`utm_*`, `fbclid`, and similar) on load.

## Writing the tellings

A telling is 3 to 5 beats. Each beat is spoken on its own, so each must stand alone.

- At most 75 words per beat, counted after the proverb text is inserted.
- No quotation marks. Greeo never puts words in anyone's mouth.
- No added facts. Every number (as digits) and every name must appear in the event
  title, the facts or the context.
- No invented scenes about real people and no invented dialogue.
- Proverbs appear only as slots, `{{P1}}`. Each mapped slot appears exactly once in
  each telling. The server inserts the verified proverb's spoken form.
- Phrases that credit tradition, such as *the elders say*, *an old proverb says* or
  *as the saying goes*, may only come directly before a proverb slot. Otherwise Greeo
  would present its own words as traditional wisdom.
- No phrase from `data/banned_phrases.txt`.
- Voice follows `docs/GRIOT_STYLE_GUIDE.md`: no faux dialect, no treating Africa as one
  voice. A proverb's culture is named by its own record, never by the telling.

### The closing

`closing_kind` is `moral`, `reflection` or `none`. `closing_text` is at most 200
characters, and empty when the kind is `none`.

A closing may speak to a broad human theme. It must not judge a real person,
organisation, community or side as right or wrong, guess at motives, or draw a lesson
the evidence does not support. For sensitive or contested events, use a neutral
reflection, or `none` when no responsible line fits.

### Sensitive events

A `sensitive` event may not have a light telling, may not use proverbs, may not use a
moral (reflection or none only), and its closing may not name anyone or anywhere.

## What the checks cannot see

The checks are deterministic, so they have limits. You are the final check on these:

- Numbers written as words (*three*) are not checked; only digits are.
- A name at the very start of a sentence is not recognised as a name.
- Names are matched word by word, so *North Lagos* passes if *North* and *Lagos* each
  appear somewhere in the facts.
- Whether a closing takes a side or infers a motive cannot be judged by code. The
  checker agent in the editorial pipeline will review generated tellings for this;
  curated tellings rely on your judgement.
