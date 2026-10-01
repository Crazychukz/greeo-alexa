"""Production settings must refuse unsafe configuration before the app starts."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_settings(module: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    """Import a settings module in a fresh interpreter so module-level checks run."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"DJANGO_SECRET_KEY", "ALLOW_SYNTHETIC"}
    }
    env.update({"DATABASE_URL": "postgresql://user:pass@localhost:5432/db", **overrides})
    code = f"import {module} as s; print(s.ALLOW_SYNTHETIC)"
    return subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
    )


def test_prod_refuses_the_default_secret_key() -> None:
    result = load_settings("config.settings.prod")

    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY" in result.stderr


def test_prod_never_allows_synthetic_stories() -> None:
    result = load_settings(
        "config.settings.prod", DJANGO_SECRET_KEY="synthetic-test-secret", ALLOW_SYNTHETIC="true"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_dev_shows_synthetic_stories_by_default() -> None:
    assert load_settings("config.settings.dev").stdout.strip() == "True"


def test_missing_database_url_fails_loudly() -> None:
    env = {key: value for key, value in os.environ.items() if key != "DATABASE_URL"}
    missing = subprocess.run(
        [sys.executable, "-c", "import config.settings.dev"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )

    assert missing.returncode != 0
    assert "Set the DATABASE_URL environment variable." in missing.stderr


def test_prod_never_trusts_the_dev_identity_header() -> None:
    code = "import config.settings.prod as s; print(s.MCP_ALLOW_DEV_IDENTITY)"
    env = {key: value for key, value in os.environ.items() if key != "MCP_ALLOW_DEV_IDENTITY"}
    env.update(
        DATABASE_URL="postgresql://user:pass@localhost:5432/db",
        DJANGO_SECRET_KEY="synthetic-test-secret",
        MCP_ALLOW_DEV_IDENTITY="true",
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
