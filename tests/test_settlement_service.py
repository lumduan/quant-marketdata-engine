"""Tests for the TFEX settlement service (settfex mocked — no live network)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest
from src.quant_marketdata_engine.settlement import service as service_mod
from src.quant_marketdata_engine.settlement.errors import SettlementFetchError
from src.quant_marketdata_engine.settlement.models import SettlementQuote
from src.quant_marketdata_engine.settlement.service import SettlementService, cache_key

from tests._fakes import FakeRedis


@dataclass
class FakeStats:
    """A minimal stand-in for settfex ``TradingStatistics`` (float fields)."""

    symbol: str = "S50M26"
    settlement_price: float | None = 1032.9
    prior_settlement_price: float | None = 1029.0
    theoretical_price: float | None = 1031.5
    im: float | None = 9450.0
    mm: float | None = 6615.0


def _patch_settfex(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: object | None = None,
    raises: Exception | None = None,
    counter: list[int] | None = None,
) -> None:
    """Patch ``get_trading_statistics`` where the service imports it."""

    async def _fake(symbol: str) -> object:
        if counter is not None:
            counter.append(1)
        if raises is not None:
            raise raises
        return result if result is not None else FakeStats(symbol=symbol)

    # The service imports lazily from settfex; patch the source module so the
    # lazy `from settfex... import get_trading_statistics` picks up the fake.
    import settfex.services.tfex.trading_statistics as ts_mod

    monkeypatch.setattr(ts_mod, "get_trading_statistics", _fake)


# ---- fetch: field mapping + Decimal conversion --------------------------


async def test_fetch_maps_fields_to_decimal(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(monkeypatch, result=FakeStats())
    svc = SettlementService(None)
    quote = await svc.fetch("S50M26")
    assert quote.symbol == "S50M26"
    # Float 1032.9 → exact Decimal string (no binary-float noise).
    assert str(quote.settlement_price) == "1032.9"
    assert str(quote.prior_settlement_price) == "1029.0"
    assert str(quote.theoretical_price) == "1031.5"
    assert str(quote.im) == "9450.0"
    assert str(quote.mm) == "6615.0"
    assert quote.as_of.tzinfo is not None


async def test_fetch_handles_none_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(
        monkeypatch,
        result=FakeStats(settlement_price=None, im=None, mm=None, theoretical_price=None),
    )
    quote = await SettlementService(None).fetch("S50U26")
    assert quote.settlement_price is None
    assert quote.im is None and quote.mm is None and quote.theoretical_price is None


async def test_fetch_wraps_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(monkeypatch, raises=ValueError("boom"))
    with pytest.raises(SettlementFetchError) as exc:
        await SettlementService(None).fetch("S50M26")
    assert exc.value.status_code is None


async def test_fetch_wraps_http_status_error_with_code(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "https://www.tfex.co.th/x")
    response = httpx.Response(404, request=request)
    _patch_settfex(
        monkeypatch,
        raises=httpx.HTTPStatusError("not found", request=request, response=response),
    )
    with pytest.raises(SettlementFetchError) as exc:
        await SettlementService(None).fetch("NOPE")
    assert exc.value.status_code == 404


# ---- get: read-through cache --------------------------------------------


async def test_get_caches_then_serves_from_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    redis = FakeRedis()
    svc = SettlementService(redis, cache_ttl_seconds=3600)  # type: ignore[arg-type]

    first = await svc.get("S50M26")
    assert str(first.settlement_price) == "1032.9"
    assert len(calls) == 1  # cold fetch ran once
    assert cache_key("S50M26") in redis.store  # write-through happened

    second = await svc.get("S50M26")
    assert str(second.settlement_price) == "1032.9"
    assert len(calls) == 1  # second call served from Redis — no second fetch


async def test_get_round_trips_decimal_through_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    _patch_settfex(monkeypatch)
    redis = FakeRedis()
    svc = SettlementService(redis)  # type: ignore[arg-type]
    await svc.get("S50M26")
    # Force the second call to come from Redis only.
    monkeypatch.setattr(service_mod.SettlementService, "fetch", _raising_fetch)
    served = await svc.get("S50M26")
    assert isinstance(served.settlement_price, Decimal)
    assert str(served.settlement_price) == "1032.9"
    assert str(served.im) == "9450.0"


async def _raising_fetch(self: SettlementService, symbol: str) -> SettlementQuote:
    raise AssertionError("fetch should not be called on a cache hit")


async def test_get_no_redis_fetches_every_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    svc = SettlementService(None)
    await svc.get("S50M26")
    await svc.get("S50M26")
    assert len(calls) == 2  # no cache → two fetches


async def test_get_degrades_when_redis_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    redis = FakeRedis(fail=True)  # get/set both raise
    svc = SettlementService(redis)  # type: ignore[arg-type]
    quote = await svc.get("S50M26")  # must still serve via live fetch
    assert str(quote.settlement_price) == "1032.9"
    assert len(calls) == 1


async def test_get_decode_error_treated_as_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    redis = FakeRedis()
    redis.store[cache_key("S50M26")] = "not-json{"  # corrupt cache entry
    svc = SettlementService(redis)  # type: ignore[arg-type]
    quote = await svc.get("S50M26")  # decode fails → miss → live fetch
    assert str(quote.settlement_price) == "1032.9"
    assert len(calls) == 1


async def test_get_lock_recheck_serves_concurrent_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settfex(monkeypatch)
    redis = FakeRedis()
    svc = SettlementService(redis)  # type: ignore[arg-type]
    # Pre-seed the cache *after* the first miss is forced: patch _get_cached to
    # miss once (outer check) then hit (post-lock re-check), exercising line 125.
    outer: list[int] = []
    cached_quote = await svc.fetch("S50M26")

    async def _miss_then_hit(symbol: str) -> SettlementQuote | None:
        outer.append(1)
        if len(outer) == 1:
            return None  # outer check: miss
        return cached_quote  # post-lock re-check: hit (line 125)

    monkeypatch.setattr(svc, "_get_cached", _miss_then_hit)
    served = await svc.get("S50M26")
    assert str(served.settlement_price) == "1032.9"
    assert len(outer) == 2  # outer miss + post-lock re-check hit


async def test_set_cached_with_zero_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(monkeypatch)
    redis = FakeRedis()
    svc = SettlementService(redis, cache_ttl_seconds=0)  # type: ignore[arg-type]
    await svc.get("S50M26")  # ttl<=0 → set without ex (line 156)
    assert cache_key("S50M26") in redis.store
