"""Tests for the tvkit client wrapper (the live OHLCV class is monkeypatched)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from src.quant_marketdata_engine.ingest import tvkit_client
from src.quant_marketdata_engine.ingest.errors import TvkitFetchError


class _FakeBar:
    def __init__(self, ts: float, o: float, h: float, low: float, c: float, v: float) -> None:
        self.timestamp = ts
        self.open = o
        self.high = h
        self.low = low
        self.close = c
        self.volume = v


def _make_fake_ohlcv(bars: list[_FakeBar] | None = None, *, raise_exc: bool = False) -> type:
    class _FakeOHLCV:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.cookies = kwargs.get("cookies")

        async def __aenter__(self) -> _FakeOHLCV:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def get_historical_ohlcv(self, symbol: str, **kwargs: Any) -> list[_FakeBar]:
            if raise_exc:
                raise RuntimeError("session expired: secretcookie")
            return bars or []

    return _FakeOHLCV


async def test_unsupported_timeframe_raises() -> None:
    with pytest.raises(TvkitFetchError, match="unsupported timeframe"):
        await tvkit_client.fetch_ohlcv(symbol="X", timeframe="2h", cookies={})


async def test_fetch_maps_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    epoch = datetime(2026, 5, 29, tzinfo=UTC).timestamp()
    fake = _make_fake_ohlcv([_FakeBar(epoch, 10.0, 11.0, 9.0, 10.5, 1000.0)])
    monkeypatch.setattr(tvkit_client, "OHLCV", fake)
    rows = await tvkit_client.fetch_ohlcv(
        symbol="SET:PTT", timeframe="1d", cookies={"sessionid": "x"}, bars_count=10
    )
    assert len(rows) == 1
    assert rows[0].open == Decimal("10.0")
    assert rows[0].ts == datetime(2026, 5, 29, tzinfo=UTC)
    assert rows[0].open_interest is None


async def test_fetch_error_wrapped_without_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _make_fake_ohlcv(raise_exc=True)
    monkeypatch.setattr(tvkit_client, "OHLCV", fake)
    with pytest.raises(TvkitFetchError) as exc:
        await tvkit_client.fetch_ohlcv(
            symbol="SET:PTT", timeframe="5m", cookies={"sessionid": "secretcookie"}
        )
    # The error wraps context but the cookie dict itself is never formatted in.
    assert "SET:PTT" in str(exc.value)
