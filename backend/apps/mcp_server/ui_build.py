"""Compose each card into one self-contained HTML file (no build tools, no dependencies).

`src/base.html` holds the shared design system and the MCP Apps bridge; each
`src/cards/<name>.html` holds one `<style>` and one `<script>` block. The output in
`dist/` is committed, so the server needs no build step and a test can prove it is fresh.
"""

from __future__ import annotations

import re
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
SRC_DIR = UI_DIR / "src"
DIST_DIR = UI_DIR / "dist"
MAX_CARD_BYTES = 50_000

# Card name -> (title, one-line description for resources/list).
CARDS: dict[str, tuple[str, str]] = {
    "tale": ("The tale", "The current beat of a tale, with its proverb and progress."),
    "wisdom": ("The wisdom", "The closing thought and each proverb's culture, meaning and source."),
    "facts": ("The facts", "What actually happened, with who reported it and when."),
    "context": ("The background", "Background, why it matters and what it could mean."),
    "perspectives": ("Perspectives", "Sourced viewpoints on the story, side by side."),
    "sources": ("The sources", "Evidence cards grouped by what they support."),
}

STYLE_BLOCK = re.compile(r"<style>(.*?)</style>", re.DOTALL)
SCRIPT_BLOCK = re.compile(r"<script>(.*?)</script>", re.DOTALL)


def card_uri(name: str) -> str:
    return f"ui://greeo/{name}"


def build_card(name: str) -> str:
    """Return the complete HTML for one card."""
    title, _ = CARDS[name]
    base = (SRC_DIR / "base.html").read_text(encoding="utf-8")
    partial = (SRC_DIR / "cards" / f"{name}.html").read_text(encoding="utf-8")
    style = STYLE_BLOCK.search(partial)
    script = SCRIPT_BLOCK.search(partial)
    if style is None or script is None:
        raise ValueError(f"Card partial {name!r} needs one <style> and one <script> block.")
    return (
        base.replace("/*__CARD_CSS__*/", style.group(1).strip())
        .replace("/*__CARD_JS__*/", script.group(1).strip())
        .replace("__CARD_NAME__", name)
        .replace("__CARD_TITLE__", title)
    )


def build_all() -> dict[str, str]:
    return {name: build_card(name) for name in CARDS}


def write_dist() -> list[Path]:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for name, html in build_all().items():
        path = DIST_DIR / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        written.append(path)
    return written


def stale_cards() -> list[str]:
    """Cards whose committed dist file differs from a fresh build."""
    stale = []
    for name, html in build_all().items():
        path = DIST_DIR / f"{name}.html"
        if not path.exists() or path.read_text(encoding="utf-8") != html:
            stale.append(name)
    return stale


def read_dist(name: str) -> str:
    return (DIST_DIR / f"{name}.html").read_text(encoding="utf-8")
