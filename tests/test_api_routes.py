"""Tests for the read API + owner-mode admin route (fakes via overrides)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.quant_marketdata_engine.api import deps, routes
from src.quant_marketdata_engine.api.main import create_app
from src.quant_marketdata_engine.cache import ohlcv_cache
from src.quant_marketdata_engine.config.settings import Settings
from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.ingest.errors import IngestDisabledError, TvkitFetchError

from tests._fakes import FakeConn, FakePool, FakeRedis, make_bar_record


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[call-arg]


def _client(*, settings: Settings, pool: Any = None, redis: Any = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[deps.get_settings_dep] = lambda: settings
    app.dependency_overrides[deps.get_pool_dep] = lambda: pool
    app.dependency_overrides[deps.get_redis_dep] = lambda: redis
    return TestClient(app)  # no context manager → lifespan not run


# ---- health -------------------------------------------------------------


def test_health_degraded_when_deps_down() -> None:
    client = _client(settings=_settings())
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["db"] is False and body["redis"] is False
    assert body["cookie_present"] is False


def test_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _pg_ok(_pool: Any) -> bool:
        return True

    async def _redis_ok(_client: Any) -> bool:
        return True

    monkeypatch.setattr(routes, "get_pool", lambda: FakePool(FakeConn()))
    monkeypatch.setattr(routes, "pg_ping", _pg_ok)
    monkeypatch.setattr(routes, "get_redis", lambda: FakeRedis())
    monkeypatch.setattr(routes, "redis_ping", _redis_ok)
    client = _client(settings=_settings(tvkit_auth_token='{"sessionid": "x"}'))
    body = client.get("/health").json()
    assert body == {"status": "ok", "db": True, "redis": True, "cookie_present": True}


# ---- /ohlcv -------------------------------------------------------------


def test_ohlcv_warm_path_serializes_decimal_as_string() -> None:
    pool = FakePool(FakeConn(fetch_result=[make_bar_record(open_interest="42.0000")]))
    client = _client(settings=_settings(), pool=pool, redis=None)
    resp = client.get("/ohlcv", params={"symbol": "SET:PTT", "timeframe": "1d"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["adjusted"] is False
    assert body["bars"][0]["open"] == "10.000000"
    assert body["bars"][0]["open_interest"] == "42.0000"


def test_ohlcv_cache_hit_skips_db() -> None:
    import asyncio

    redis = FakeRedis()
    key = ohlcv_cache.make_key(
        symbol="X", timeframe="1d", adjusted=False, start=None, end=None, limit=5000
    )
    bar = OHLCVBarRow(**make_bar_record(symbol="X"))
    asyncio.run(ohlcv_cache.set_cached_bars(redis, key, [bar], 300))  # type: ignore[arg-type]
    # DB would raise if touched — proves the cache served.
    pool = FakePool(FakeConn(raise_on={"fetch"}))
    client = _client(settings=_settings(), pool=pool, redis=redis)
    resp = client.get("/ohlcv", params={"symbol": "X", "timeframe": "1d"})
    assert resp.status_code == 200
    # Cache served (DB fetch would have raised); top-level symbol echoes the request.
    assert resp.json()["symbol"] == "X"
    assert len(resp.json()["bars"]) == 1


def test_ohlcv_adjusted_uses_view() -> None:
    pool = FakePool(FakeConn(fetch_result=[make_bar_record()]))
    client = _client(settings=_settings(), pool=pool, redis=None)
    resp = client.get("/ohlcv/adjusted", params={"symbol": "SET:PTT", "timeframe": "1d"})
    assert resp.status_code == 200 and resp.json()["adjusted"] is True


def test_ohlcv_invalid_timeframe_422() -> None:
    client = _client(settings=_settings(), pool=FakePool(FakeConn()))
    resp = client.get("/ohlcv", params={"symbol": "X", "timeframe": "2h"})
    assert resp.status_code == 422


def test_ohlcv_start_after_end_422() -> None:
    client = _client(settings=_settings(), pool=FakePool(FakeConn()), redis=None)
    resp = client.get(
        "/ohlcv",
        params={
            "symbol": "X",
            "timeframe": "1d",
            "start": "2026-06-01T00:00:00Z",
            "end": "2026-05-01T00:00:00Z",
        },
    )
    assert resp.status_code == 422


def test_ohlcv_bad_limit_422() -> None:
    client = _client(settings=_settings(), pool=FakePool(FakeConn()))
    resp = client.get("/ohlcv", params={"symbol": "X", "timeframe": "1d", "limit": 0})
    assert resp.status_code == 422


# ---- auth ---------------------------------------------------------------


def test_auth_required_when_key_set() -> None:
    client = _client(settings=_settings(api_key="secret"), pool=FakePool(FakeConn()))
    assert client.get("/ohlcv", params={"symbol": "X", "timeframe": "1d"}).status_code == 401


def test_auth_passes_with_correct_key() -> None:
    pool = FakePool(FakeConn(fetch_result=[]))
    client = _client(settings=_settings(api_key="secret"), pool=pool, redis=None)
    resp = client.get(
        "/ohlcv", params={"symbol": "X", "timeframe": "1d"}, headers={"X-API-Key": "secret"}
    )
    assert resp.status_code == 200


# ---- DB unavailable -----------------------------------------------------


def test_get_pool_dep_maps_uninitialized_to_503() -> None:
    import pytest as _pytest
    from fastapi import HTTPException

    # conftest resets the module pool to None before each test.
    with _pytest.raises(HTTPException) as exc:
        deps.get_pool_dep()
    assert exc.value.status_code == 503


# ---- /universe ----------------------------------------------------------


def test_universe() -> None:
    conn = FakeConn(fetchval_result=date(2026, 4, 30), fetch_result=[{"symbol": "SET:AOT"}])
    client = _client(settings=_settings(), pool=FakePool(conn))
    resp = client.get("/universe", params={"as_of": "2026-05-15"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of"] == "2026-04-30" and body["symbols"] == ["SET:AOT"]


# ---- /admin/ingest ------------------------------------------------------


def _ingest_body() -> dict[str, Any]:
    return {"symbol": "SET:PTT", "timeframe": "1d", "bars": 10}


def test_admin_ingest_forbidden_in_public_mode() -> None:
    client = _client(settings=_settings(public_mode=True), pool=FakePool(FakeConn()))
    assert client.post("/admin/ingest", json=_ingest_body()).status_code == 403


def test_admin_ingest_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_ingest(**_: Any) -> int:
        return 4

    monkeypatch.setattr(routes, "ingest_ohlcv", _fake_ingest)
    client = _client(settings=_settings(public_mode=False), pool=FakePool(FakeConn()), redis=None)
    resp = client.post("/admin/ingest", json=_ingest_body())
    assert resp.status_code == 200 and resp.json()["rows_written"] == 4


def test_admin_ingest_upstream_failure_502(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(**_: Any) -> int:
        raise TvkitFetchError("upstream")

    monkeypatch.setattr(routes, "ingest_ohlcv", _boom)
    client = _client(settings=_settings(public_mode=False), pool=FakePool(FakeConn()), redis=None)
    assert client.post("/admin/ingest", json=_ingest_body()).status_code == 502


def test_admin_ingest_other_error_400(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _disabled(**_: Any) -> int:
        raise IngestDisabledError("nope")

    monkeypatch.setattr(routes, "ingest_ohlcv", _disabled)
    client = _client(settings=_settings(public_mode=False), pool=FakePool(FakeConn()), redis=None)
    assert client.post("/admin/ingest", json=_ingest_body()).status_code == 400
