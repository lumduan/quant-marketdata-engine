"""Tests for the single-flight Redis lock primitive."""

from __future__ import annotations

from src.quant_marketdata_engine.cache import single_flight

from tests._fakes import FakeRedis


def test_lock_key_shape() -> None:
    key = single_flight.lock_key(symbol="S501!", timeframe="5m", range_key="r")
    assert key == "mde:lock:S501!:5m:r"


async def test_none_client_yields_true() -> None:
    async with single_flight.single_flight(None, "k") as acquired:
        assert acquired is True


async def test_acquire_and_release() -> None:
    redis = FakeRedis()
    async with single_flight.single_flight(redis, "k", ttl_seconds=5) as acquired:  # type: ignore[arg-type]
        assert acquired is True
    assert redis.evals  # release ran the compare-and-delete script


async def test_not_acquired_when_held() -> None:
    redis = FakeRedis()
    redis.store["k"] = "someone-else"
    async with single_flight.single_flight(redis, "k") as acquired:  # type: ignore[arg-type]
        assert acquired is False
    assert not redis.evals  # we never owned it, so no release


async def test_acquire_error_proceeds() -> None:
    redis = FakeRedis(fail=True)
    async with single_flight.single_flight(redis, "k") as acquired:  # type: ignore[arg-type]
        # On Redis error we proceed (idempotent upsert keeps correctness).
        assert acquired is True
