# Proverb corpus guide

The corpus is JSON Lines (`.jsonl`): one JSON object per proverb. Do not add real entries unless you have checked their wording, attribution, citations, and reuse rights.

## Required fields

`original_text`, `language`, `spoken_form`, `translation`, `meaning_note`, `speak_original_ok`, `culture`, `region`, `source_citation`, `second_source_citation`, `license`, `verification_status`, `dispute_note`, `themes`, and `tone_ok` are required on every line.

- `original_text`: the verified wording to display on a card.
- `spoken_form`: what Greeo says aloud, normally an English translation. It is required for verified entries.
- `translation`: an accompanying translation where relevant.
- `meaning_note`: plain-language meaning and when it fits.
- `speak_original_ok`: true only when it is appropriate for the platform voice to speak the original language.
- `culture`: a specific attribution such as Yoruba, Igbo, or Akan—never `African` or `Africa`.
- `source_citation` and `second_source_citation`: independent published sources.
- `license`: reuse terms for the source collection; do not import material whose terms prohibit the intended use.
- `verification_status`: `unverified`, `single_source`, `verified`, or `disputed`.
- `dispute_note`: explain contested wording, attribution, or meaning.
- `themes`: keys from `data/themes.yaml` only.
- `tone_ok`: whether the entry may be considered for a non-sensitive telling.

An entry is **verified** only after two independent published sources support its text and attribution. Record uncertainty as `single_source` or `disputed`; neither can ever be served. The import command rejects generic cultures, unknown themes, missing verified citations, and duplicate normalised text/culture combinations. It makes no partial writes.

Use `original_text` on cards. Alexa speaks `spoken_form`, unless `speak_original_ok` is true and the product has deliberately chosen to speak the original language; platform pronunciation may be unreliable.

## Commands

```sh
python manage.py import_proverbs path/to/corpus.jsonl --dry-run
python manage.py import_proverbs path/to/corpus.jsonl
python manage.py proverb_audit
```
