"""Convert the Greeo v1 proverb files into the import_proverbs JSONL format.

DEMO CORPUS ONLY. These entries come from africanproverbs.com, used without a license
for a non-commercial hackathon demo while permission is requested. They are imported
as single_source with their source kept, are unservable unless
DEMO_ALLOW_SINGLE_SOURCE_PROVERBS is on, and must be removed after judging.
See docs/proverbs/DEMO_CORPUS.md.

Usage:
    python scripts/convert_v1_proverbs.py proverbs.json proverbs_extra.json \
        > data/proverbs/demo/africanproverbs_demo.jsonl
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SOURCE_NAME = "africanproverbs.com"
SOURCE_CITATION = (
    "africanproverbs.com (https://www.africanproverbs.com), retrieved through its "
    "public API for the Greeo v1 prototype"
)
LICENSE = (
    "Unlicensed demo use; permission requested from africanproverbs.com; "
    "remove after hackathon judging"
)

# v1 labelled each entry by language. The corpus needs a specific culture and region.
LANGUAGES = {
    "Afaan Oromo": ("Afaan Oromo", "Oromo", "Ethiopia and Kenya"),
    "Akan": ("Akan (Twi)", "Akan", "Ghana"),
    "Amharic": ("Amharic", "Amhara", "Ethiopia"),
    "Fulfulde": ("Fulfulde", "Fulani", "West Africa and the Sahel"),
    "Hausa": ("Hausa", "Hausa", "Nigeria and Niger"),
    "Igbo": ("Igbo", "Igbo", "Nigeria"),
    "IsiZulu": ("isiZulu", "Zulu", "South Africa"),
    "Kinyarwanda": ("Kinyarwanda", "Rwandan", "Rwanda"),
    "Kiswahili": ("Kiswahili", "Swahili", "East Africa"),
    "Lingala": ("Lingala", "Lingala-speaking peoples of the Congo Basin", "Congo"),
    "Shona": ("chiShona", "Shona", "Zimbabwe"),
    "Somali": ("Somali", "Somali", "Horn of Africa"),
    "Wolof": ("Wolof", "Wolof", "Senegal and The Gambia"),
    "Xhosa": ("isiXhosa", "Xhosa", "South Africa"),
    "Yoruba": ("Yoruba", "Yoruba", "Nigeria and Benin"),
}

# Only v1 themes with a clear equivalent in data/themes.yaml are kept.
THEMES = {
    "change": "change",
    "community": "community",
    "humility": "humility",
    "justice": "justice",
    "patience": "patience",
    "resilience": "resilience",
    "greed": "self_interest",
    "caution": "prudence",
}


def clean(text: str) -> str:
    """Collapse whitespace and repair the v1 double-apostrophe opening quote."""
    return re.sub(r"\s+", " ", text.replace("''", "“")).strip()


def convert(entries: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Return import rows plus counts of what was skipped and why."""
    rows: list[dict] = []
    skipped = {"not_from_source": 0, "unknown_language": 0, "missing_text": 0, "duplicate": 0}
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if entry.get("source") != SOURCE_NAME:
            skipped["not_from_source"] += 1
            continue
        mapping = LANGUAGES.get(entry.get("ethnic", "").strip())
        if mapping is None:
            skipped["unknown_language"] += 1
            continue
        original = clean(entry.get("text", ""))
        english = clean(entry.get("transliteration", ""))
        meaning = clean(entry.get("meaning", ""))
        if not (original and english and meaning):
            skipped["missing_text"] += 1
            continue
        language, culture, region = mapping
        key = (re.sub(r"\s+", " ", original.casefold()), culture.casefold())
        if key in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(key)
        rows.append(
            {
                "original_text": original,
                "language": language,
                "spoken_form": english,
                "translation": english,
                "meaning_note": meaning,
                "speak_original_ok": False,
                "culture": culture,
                "region": region,
                "source_citation": SOURCE_CITATION,
                "second_source_citation": "",
                "license": LICENSE,
                "verification_status": "single_source",
                "dispute_note": "",
                "themes": sorted({THEMES[t] for t in entry.get("themes", []) if t in THEMES}),
                # Every entry needs a human tone review before it can be served.
                "tone_ok": False,
            }
        )
    return rows, skipped


def main(paths: list[str]) -> None:
    entries: list[dict] = []
    for path in paths:
        entries.extend(json.loads(Path(path).read_text(encoding="utf-8")))
    rows, skipped = convert(entries)
    for row in rows:
        sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"converted={len(rows)} skipped={skipped}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
