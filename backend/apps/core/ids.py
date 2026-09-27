"""Stable public identifiers for records passed between product layers."""

from __future__ import annotations

from uuid import uuid4


def prefixed_id(prefix: str) -> str:
    """Return a compact opaque identifier while keeping its domain recognizable."""
    return f"{prefix}{uuid4().hex[:12]}"


def story_id() -> str:
    """Create the public identifier format used by story tools."""
    return prefixed_id("st_")


def proverb_id() -> str:
    """Create the public identifier format used by proverb tools."""
    return prefixed_id("pv_")
