from __future__ import annotations

from apps.core.tasks import ping
from config.celery import app
from django.test import override_settings


def test_core_ping_is_discoverable_by_celery() -> None:
    app.loader.import_default_modules()

    assert "core.ping" in app.tasks


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
def test_core_ping_runs_eagerly() -> None:
    assert ping.delay().get() == "pong"
