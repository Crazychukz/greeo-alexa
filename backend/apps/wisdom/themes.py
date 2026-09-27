"""Controlled theme-vocabulary loading shared by corpus and editorial code."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@lru_cache
def theme_vocabulary() -> dict[str, str]:
    """Load reviewed theme keys rather than allowing free-form model labels."""
    path = Path(settings.BASE_DIR).parent / "data" / "themes.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ImproperlyConfigured(f"Theme vocabulary is unavailable at {path}.") from exc
    if not isinstance(data, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in data.items()
    ):
        raise ImproperlyConfigured("themes.yaml must map string keys to string definitions.")
    return data


def validate_theme_keys(themes: list[str]) -> None:
    """Reject labels that are outside the reviewed vocabulary."""
    unknown = sorted(set(themes) - theme_vocabulary().keys())
    if unknown:
        raise ValueError(f"Unknown theme key(s): {', '.join(unknown)}")
