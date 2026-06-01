"""Tests for the Redis client lifecycle helpers."""

from __future__ import annotations

import pytest
import redis.asyncio as aioredis
from src.quant_marketdata_engine.cache import redis_client

from tests._fakes import FakeRedis


async def test_get_redis_none_when_uninitialized() -> None:
    assert redis_client.get_redis() is None


async def test_close_redis_noop_when_uninitialized() -> None:
    await redis_client.close_redis()  # must not raise


async def test_create_get_close(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRedis()
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: fake)
    created = redis_client.create_redis("redis://x")
    assert isinstance(created, FakeRedis)
    assert redis_client.create_redis("redis://x") is created  # cached
    assert redis_client.get_redis() is created
    await redis_client.close_redis()
    assert fake.closed is True


async def test_ping_true_false() -> None:
    assert await redis_client.ping(FakeRedis()) is True  # type: ignore[arg-type]
    assert await redis_client.ping(FakeRedis(fail=True)) is False  # type: ignore[arg-type]
