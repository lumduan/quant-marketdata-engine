"""Lifespan coverage for the FastAPI app (IO monkeypatched)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.quant_marketdata_engine.api import main


def test_lifespan_opens_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    async def _fake_create_pool(*a: Any, **k: Any) -> None:
        events.append("pool")

    async def _fake_close_pool() -> None:
        events.append("close_pool")

    async def _fake_close_redis() -> None:
        events.append("close_redis")

    monkeypatch.setattr(main, "create_pool", _fake_create_pool)
    monkeypatch.setattr(main, "create_redis", lambda *a, **k: events.append("redis"))
    monkeypatch.setattr(main, "close_pool", _fake_close_pool)
    monkeypatch.setattr(main, "close_redis", _fake_close_redis)

    with TestClient(main.create_app()):  # runs startup + shutdown
        pass

    assert events == ["pool", "redis", "close_redis", "close_pool"]


def test_lifespan_survives_pool_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(*a: Any, **k: Any) -> None:
        raise OSError("db down")

    async def _noop() -> None:
        return None

    monkeypatch.setattr(main, "create_pool", _boom)
    monkeypatch.setattr(main, "create_redis", lambda *a, **k: None)
    monkeypatch.setattr(main, "close_pool", _noop)
    monkeypatch.setattr(main, "close_redis", _noop)

    # Startup must not crash even when the DB is unreachable.
    with TestClient(main.create_app()):
        pass
