"""Words Greeo must never say aloud, shared by the MCP voice gate and the content loaders.

Alexa+ requires that no tool names, JSON, API codes or internal ids reach customers.
Keeping the list in one place means story text is rejected when it is curated or
generated, instead of failing when a listener asks for it.
"""

from __future__ import annotations

import re

FORBIDDEN_VOCABULARY = (
    "tool",
    "json",
    "api",
    "error code",
    "exception",
    "traceback",
    "story_id",
    "undefined",
    "null",
)
FORBIDDEN_PATTERN = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(word) for word in FORBIDDEN_VOCABULARY) + r")(?![\w-])",
    re.IGNORECASE,
)


def forbidden_words(text: str) -> list[str]:
    """Whole-word, case-insensitive matches, in order and without repeats."""
    return list(dict.fromkeys(match.lower() for match in FORBIDDEN_PATTERN.findall(text)))
