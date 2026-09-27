"""Load versioned prompt assets without embedding editorial wording in code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from .exceptions import LLMError


@dataclass(frozen=True)
class PromptDefinition:
    """A prompt asset together with the version encoded in its filename."""

    name: str
    version: str
    text: str


def load_prompt(prompt_name: str) -> PromptDefinition:
    """Read a registered prompt and reject path-like or unversioned names."""
    if not prompt_name.replace("_", "").isalnum():
        raise LLMError(f"Invalid prompt name: {prompt_name!r}.")

    prompt_dir = Path(settings.BASE_DIR) / "apps" / "llm" / "prompts"
    matches = sorted(prompt_dir.glob(f"{prompt_name}.v*.md"))
    if len(matches) != 1:
        raise LLMError(f"Prompt {prompt_name!r} must have exactly one versioned asset.")

    path = matches[0]
    version = path.stem.removeprefix(f"{prompt_name}.")
    return PromptDefinition(
        name=prompt_name, version=version, text=path.read_text(encoding="utf-8")
    )
