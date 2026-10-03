# Demo proverb corpus

Greeo's product rule is that only **verified** proverbs (two independent citations) are
spoken. For the hackathon demo, a larger single-source corpus is used under a switch
that is off by default. This page records what it is, how it is used, and how it is
removed.

## What it is

- 594 proverbs in 15 languages, collected for the Greeo v1 prototype from
  [africanproverbs.com](https://www.africanproverbs.com) through its public API.
- Each entry keeps its source in `source_citation`; the source is never removed.
- `verification_status` is `single_source`; `second_source_citation` is empty.
- `license` records the position: unlicensed demo use, permission requested, remove
  after judging. africanproverbs.com's terms restrict copying and public display, so
  permission has been requested (see below).
- Every entry imports with `tone_ok = false`. A person must read and approve each
  proverb (admin action *Approve tone for selected proverbs*) before it can be used.
  On 2026-10-01 the owner approved the whole corpus at once with
  `python manage.py trust_proverbs` (undo with `--undo`), and the writer now chooses
  among all of them by meaning. Disputed or poor entries can still be un-approved
  one by one in the admin.
- The sayings are traditional; the English translations and meaning notes are the
  site's.

## How it is used

- The data file `data/proverbs/demo/africanproverbs_demo.jsonl` is gitignored while
  the GitHub repository is public. Commit it only after the repository is private.
- It is produced from the v1 files by `scripts/convert_v1_proverbs.py`, which keeps
  only africanproverbs.com entries with a known language, a translation and a meaning,
  maps each language to a specific culture and region, and keeps only v1 themes with
  an equivalent in `data/themes.yaml`.
- `DEMO_ALLOW_SINGLE_SOURCE_PROVERBS=true` lets single-source, tone-approved proverbs
  be served. Retrieval, publication and rendering all read the same rule
  (`apps/wisdom/managers.py`, `servable_statuses`).
- Proverb cards carry `source_citation` and `verification_status`, so a listener can
  always hear or see where a proverb came from.

```sh
python scripts/convert_v1_proverbs.py proverbs.json proverbs_extra.json \
  > data/proverbs/demo/africanproverbs_demo.jsonl
docker compose exec web python manage.py import_proverbs ../data/proverbs/demo/africanproverbs_demo.jsonl
```

## Disclosure for the submission

Include wording like this in the Devpost description and the README while the switch
is on:

> The demo uses a single-source proverb corpus from africanproverbs.com, credited on
> every proverb card. In production Greeo serves only proverbs verified against two
> independent citations; the demo switch that relaxes this is off by default.

## Permission request

- Sent to: contact@calmglobal.com (the contact in africanproverbs.com's terms)
- Date sent: _fill in_
- Reply: _fill in_

If permission is granted, record it in each entry's `license` field and keep the
source citation. If it is refused, remove the corpus immediately.

## Removal after judging

1. Set `DEMO_ALLOW_SINGLE_SOURCE_PROVERBS=false`.
2. Delete the data file and remove the entries:
   `Proverb.objects.filter(source_citation__startswith="africanproverbs.com").delete()`
   (tellings that use one must be unpublished or re-slotted first; the foreign key
   is protected).
3. Remove the file from git history if it was committed, and delete this page's
   "How it is used" section.
