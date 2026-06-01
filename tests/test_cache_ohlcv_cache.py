"""Tests for the write-through OHLCV hot-window cache."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from src.quant_marketdata_engine.cache import ohlcv_cache
from src.quant_marketdata_engine.db.models import OHLCVBarRow

from tests._fakes import FakeRedis


def _bar() -> OHLCVBarRow:
    return OHLCVBarRow(
        symbol="SET:PTT",
        timeframe="1d",
        ts=datetime(2026, 5, 29, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        open_interest=Decimal("5"),
    )


def test_make_key_stable_and_variant() -> None:
    raw = ohlcv_cache.make_key(
        symbol="X", timeframe="1d", adjusted=False, start=None, end=None, limit=10
    )
    adj = ohlcv_cache.make_key(
        symbol="X", timeframe="1d", adjusted=True, start=None, end=None, limit=10
    )
    assert raw == "mde:ohlcv:raw:X:1d:-:-:10"
    assert ":raw:" in raw and ":adj:" in adj
    assert raw != adj


def test_get_cached_none_client_returns_none() -> None:
    import asyncio

    assert asyncio.run(ohlcv_cache.get_cached_bars(None, "k")) is None


async def test_write_through_roundtrip() -> None:
    redis = FakeRedis()
    key = "k1"
    await ohlcv_cache.set_cached_bars(redis, key, [_bar()], 300)  # type: ignore[arg-type]
    got = await ohlcv_cache.get_cached_bars(redis, key)  # type: ignore[arg-type]
    assert got is not None and len(got) == 1
    assert got[0].open == Decimal("10")
    assert got[0].open_interest == Decimal("5")


async def test_set_cached_no_ttl() -> None:
    redis = FakeRedis()
    await ohlcv_cache.set_cached_bars(redis, "k2", [_bar()], 0)  # type: ignore[arg-type]
    assert "k2" in redis.store


async def test_get_miss_returns_none() -> None:
    assert await ohlcv_cache.get_cached_bars(FakeRedis(), "absent") is None  # type: ignore[arg-type]


async def test_get_error_degrades() -> None:
    assert await ohlcv_cache.get_cached_bars(FakeRedis(fail=True), "k") is None  # type: ignore[arg-type]


async def test_get_bad_payload_degrades() -> None:
    redis = FakeRedis()
    redis.store["bad"] = "{not json"
    assert await ohlcv_cache.get_cached_bars(redis, "bad") is None  # type: ignore[arg-type]


async def test_set_error_degrades() -> None:
    await ohlcv_cache.set_cached_bars(FakeRedis(fail=True), "k", [_bar()], 300)  # type: ignore[arg-type]


async def test_set_none_client_noop() -> None:
    await ohlcv_cache.set_cached_bars(None, "k", [_bar()], 300)


async def test_invalidate_deletes_matching() -> None:
    redis = FakeRedis()
    await ohlcv_cache.set_cached_bars(redis, "mde:ohlcv:raw:X:1d:-:-:10", [_bar()], 300)  # type: ignore[arg-type]
    removed = await ohlcv_cache.invalidate(redis, symbol="X", timeframe="1d")  # type: ignore[arg-type]
    assert removed == 1


async def test_invalidate_none_client() -> None:
    assert await ohlcv_cache.invalidate(None, symbol="X", timeframe="1d") == 0


async def test_invalidate_error_degrades() -> None:
    assert await ohlcv_cache.invalidate(FakeRedis(fail=True), symbol="X", timeframe="1d") == 0  # type: ignore[arg-type]
