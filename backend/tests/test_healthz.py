from __future__ import annotations

from apps.core import services


def test_healthz_returns_ok_when_database_and_redis_are_available(client, monkeypatch) -> None:
    monkeypatch.setattr(services, "database_status", lambda: {"status": "ok"})
    monkeypatch.setattr(services, "redis_status", lambda: {"status": "ok"})

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": {"status": "ok"},
        "redis": {"status": "ok"},
    }
