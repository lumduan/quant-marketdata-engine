"""Tests for the ingest orchestration service."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from src.quant_marketdata_engine.cache import single_flight
from src.quant_marketdata_engine.config.settings import Settings
from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.ingest import service, tvkit_client
from src.quant_marketdata_engine.ingest.errors import IngestDisabledError

from tests._fakes import FakeRedis


def _owner_settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, public_mode=False, tvkit_auth_token='{"sessionid": "x"}'
    )


def _bar() -> OHLCVBarRow:
    return OHLCVBarRow(
        symbol="SET:PTT",
        timeframe="1d",
        ts=datetime(2026, 5, 29, tzinfo=UTC),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
    )


async def test_public_mode_refuses() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    with pytest.raises(IngestDisabledError):
        await service.ingest_ohlcv(
            settings=settings,
            pool=None,
            redis=None,
            symbol="X",
            timeframe="1d",  # type: ignore[arg-type]
        )


async def test_successful_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[tuple[str, str]] = []

    async def _fake_fetch(**kw: Any) -> list[OHLCVBarRow]:
        fetched.append((kw["symbol"], kw["timeframe"]))
        return [_bar()]

    async def _fake_upsert(_pool: Any, rows: Any) -> int:
        return len(rows)

    monkeypatch.setattr(tvkit_client, "fetch_ohlcv", _fake_fetch)
    monkeypatch.setattr(service, "upsert_ohlcv", _fake_upsert)

    written = await service.ingest_ohlcv(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        symbol="SET:PTT",
        timeframe="1d",
    )
    assert written == 1
    assert fetched == [("SET:PTT", "1d")]


async def test_in_flight_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _should_not_run(**_: Any) -> list[OHLCVBarRow]:
        raise AssertionError("fetch must not run when lock is held")

    monkeypatch.setattr(tvkit_client, "fetch_ohlcv", _should_not_run)

    redis = FakeRedis()
    # Pre-hold the lock so single-flight reports "not acquired".
    key = single_flight.lock_key(symbol="SET:PTT", timeframe="1d", range_key="-:-:-")
    redis.store[key] = "held-by-other"

    written = await service.ingest_ohlcv(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=redis,  # type: ignore[arg-type]
        symbol="SET:PTT",
        timeframe="1d",
    )
    assert written == 0
