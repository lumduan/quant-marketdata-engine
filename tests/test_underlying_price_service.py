"""Tests for the TFEX underlying-price service (settfex mocked — no live network)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
import pytest
from src.quant_marketdata_engine.underlying_price import service as service_mod
from src.quant_marketdata_engine.underlying_price.errors import UnderlyingPriceFetchError
from src.quant_marketdata_engine.underlying_price.models import UnderlyingPriceQuote
from src.quant_marketdata_engine.underlying_price.service import (
    UnderlyingPriceService,
    cache_key,
)

from tests._fakes import FakeRedis

_AS_OF = datetime(2026, 6, 16, 9, 30, tzinfo=UTC)


@dataclass
class FakeUnderlying:
    """A minimal stand-in for settfex ``UnderlyingPrice`` (float + str fields).

    ``symbol`` is the **underlying** (e.g. ``SET50``), not the queried series.
    """

    symbol: str = "SET50"
    last: float | None = 1032.9
    prior: float | None = 1029.0
    high: float | None = 1035.4
    low: float | None = 1028.1
    change: float | None = 3.9
    percent_change: float | None = 0.38
    market_status: str = "Open"
    underlying_type: str = "I"
    pe: float | None = 18.2
    pbv: float | None = 1.7
    statistics_as_of: datetime = field(default_factory=lambda: _AS_OF)


def _patch_settfex(
    monkeypatch: pytest.MonkeyPatch,
    *,
    result: object | None = None,
    raises: Exception | None = None,
    counter: list[int] | None = None,
) -> None:
    """Patch ``get_underlying_price`` where the service imports it."""

    async def _fake(symbol: str) -> object:
        if counter is not None:
            counter.append(1)
        if raises is not None:
            raise raises
        return result if result is not None else FakeUnderlying()

    # The service imports lazily from settfex; patch the source module so the
    # lazy `from settfex... import get_underlying_price` picks up the fake.
    import settfex.services.tfex.underlying_price as up_mod

    monkeypatch.setattr(up_mod, "get_underlying_price", _fake)


# ---- fetch: field mapping + Decimal conversion --------------------------


async def test_fetch_maps_fields_to_decimal(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(monkeypatch, result=FakeUnderlying())
    svc = UnderlyingPriceService(None)
    quote = await svc.fetch("S50M26")
    assert quote.symbol == "S50M26"  # echoes the requested series
    assert quote.underlying_symbol == "SET50"  # the underlying instrument
    # Float 1032.9 → exact Decimal string (no binary-float noise).
    assert str(quote.last) == "1032.9"
    assert str(quote.prior) == "1029.0"
    assert str(quote.high) == "1035.4"
    assert str(quote.low) == "1028.1"
    assert str(quote.change) == "3.9"
    assert str(quote.percent_change) == "0.38"
    assert str(quote.pe) == "18.2"
    assert str(quote.pbv) == "1.7"
    assert quote.market_status == "Open"
    assert quote.underlying_type == "I"
    assert quote.as_of == _AS_OF


async def test_fetch_handles_none_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(
        monkeypatch,
        result=FakeUnderlying(last=None, prior=None, high=None, low=None, pe=None, pbv=None),
    )
    quote = await UnderlyingPriceService(None).fetch("S50U26")
    assert quote.last is None
    assert quote.prior is None and quote.high is None and quote.low is None
    assert quote.pe is None and quote.pbv is None


async def test_fetch_wraps_generic_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(monkeypatch, raises=ValueError("boom"))
    with pytest.raises(UnderlyingPriceFetchError) as exc:
        await UnderlyingPriceService(None).fetch("S50M26")
    assert exc.value.status_code is None


async def test_fetch_wraps_http_status_error_with_code(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("GET", "https://www.tfex.co.th/x")
    response = httpx.Response(404, request=request)
    _patch_settfex(
        monkeypatch,
        raises=httpx.HTTPStatusError("not found", request=request, response=response),
    )
    with pytest.raises(UnderlyingPriceFetchError) as exc:
        await UnderlyingPriceService(None).fetch("NOPE")
    assert exc.value.status_code == 404


# ---- get: read-through cache --------------------------------------------


async def test_get_caches_then_serves_from_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    redis = FakeRedis()
    svc = UnderlyingPriceService(redis, cache_ttl_seconds=60)  # type: ignore[arg-type]

    first = await svc.get("S50M26")
    assert str(first.last) == "1032.9"
    assert len(calls) == 1  # cold fetch ran once
    assert cache_key("S50M26") in redis.store  # write-through happened

    second = await svc.get("S50M26")
    assert str(second.last) == "1032.9"
    assert len(calls) == 1  # second call served from Redis — no second fetch


async def test_get_round_trips_decimal_through_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    _patch_settfex(monkeypatch)
    redis = FakeRedis()
    svc = UnderlyingPriceService(redis)  # type: ignore[arg-type]
    await svc.get("S50M26")
    # Force the second call to come from Redis only.
    monkeypatch.setattr(service_mod.UnderlyingPriceService, "fetch", _raising_fetch)
    served = await svc.get("S50M26")
    assert isinstance(served.last, Decimal)
    assert str(served.last) == "1032.9"
    assert str(served.pe) == "18.2"
    # Non-decimal fields round-trip too.
    assert served.underlying_symbol == "SET50"
    assert served.market_status == "Open"
    assert served.underlying_type == "I"
    assert served.as_of == _AS_OF


async def _raising_fetch(self: UnderlyingPriceService, symbol: str) -> UnderlyingPriceQuote:
    raise AssertionError("fetch should not be called on a cache hit")


async def test_get_no_redis_fetches_every_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    svc = UnderlyingPriceService(None)
    await svc.get("S50M26")
    await svc.get("S50M26")
    assert len(calls) == 2  # no cache → two fetches


async def test_get_degrades_when_redis_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    redis = FakeRedis(fail=True)  # get/set both raise
    svc = UnderlyingPriceService(redis)  # type: ignore[arg-type]
    quote = await svc.get("S50M26")  # must still serve via live fetch
    assert str(quote.last) == "1032.9"
    assert len(calls) == 1


async def test_get_decode_error_treated_as_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    _patch_settfex(monkeypatch, counter=calls)
    redis = FakeRedis()
    redis.store[cache_key("S50M26")] = "not-json{"  # corrupt cache entry
    svc = UnderlyingPriceService(redis)  # type: ignore[arg-type]
    quote = await svc.get("S50M26")  # decode fails → miss → live fetch
    assert str(quote.last) == "1032.9"
    assert len(calls) == 1


async def test_get_lock_recheck_serves_concurrent_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_settfex(monkeypatch)
    redis = FakeRedis()
    svc = UnderlyingPriceService(redis)  # type: ignore[arg-type]
    # Pre-seed the cache *after* the first miss is forced: patch _get_cached to
    # miss once (outer check) then hit (post-lock re-check).
    outer: list[int] = []
    cached_quote = await svc.fetch("S50M26")

    async def _miss_then_hit(symbol: str) -> UnderlyingPriceQuote | None:
        outer.append(1)
        if len(outer) == 1:
            return None  # outer check: miss
        return cached_quote  # post-lock re-check: hit

    monkeypatch.setattr(svc, "_get_cached", _miss_then_hit)
    served = await svc.get("S50M26")
    assert str(served.last) == "1032.9"
    assert len(outer) == 2  # outer miss + post-lock re-check hit


async def test_set_cached_with_zero_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settfex(monkeypatch)
    redis = FakeRedis()
    svc = UnderlyingPriceService(redis, cache_ttl_seconds=0)  # type: ignore[arg-type]
    await svc.get("S50M26")  # ttl<=0 → set without ex
    assert cache_key("S50M26") in redis.store
