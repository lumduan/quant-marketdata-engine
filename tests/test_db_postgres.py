"""Tests for the asyncpg pool lifecycle helpers."""

from __future__ import annotations

from typing import Any

import asyncpg
import pytest
from src.quant_marketdata_engine.db import postgres
from src.quant_marketdata_engine.db.errors import PoolNotInitializedError, RepositoryError

from tests._fakes import FakeConn, FakePool


async def test_get_pool_uninitialized_raises() -> None:
    with pytest.raises(PoolNotInitializedError):
        postgres.get_pool()


async def test_close_pool_noop_when_uninitialized() -> None:
    await postgres.close_pool()  # must not raise


async def test_create_get_close_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePool(FakeConn())

    async def _fake_create_pool(**_: Any) -> FakePool:
        return fake

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)
    created = await postgres.create_pool("dsn", min_size=1, max_size=3)
    assert created is fake
    # Second call returns the same pool (no re-create).
    assert await postgres.create_pool("dsn") is fake
    assert postgres.get_pool() is fake
    await postgres.close_pool()
    assert fake.closed is True


async def test_create_pool_failure_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(**_: Any) -> None:
        raise OSError("no db")

    monkeypatch.setattr(asyncpg, "create_pool", _boom)
    with pytest.raises(RepositoryError, match="failed to create"):
        await postgres.create_pool("dsn")


async def test_ping_true_and_false() -> None:
    assert await postgres.ping(FakePool(FakeConn())) is True  # type: ignore[arg-type]
    assert await postgres.ping(FakePool(FakeConn(raise_on={"execute"}))) is False  # type: ignore[arg-type]
