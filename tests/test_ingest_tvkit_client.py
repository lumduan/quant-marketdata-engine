"""Tests for the tvkit client wrapper (the live OHLCV class is monkeypatched)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
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


async def test_daily_bars_are_keyed_by_session_not_by_the_vendor_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two fetches of one session at different vendor stamps map to one key.

    TradingView moved the SET daily stamp from 09:55 to 09:00 Bangkok around
    2026-09-08 and the 30-bar refetch then duplicated its whole window. Both
    stamps must now produce the same ``ts``, so the upsert updates in place.
    """
    bkk = timezone(timedelta(hours=7))
    old_stamp = datetime(2026, 9, 4, 9, 55, tzinfo=bkk).timestamp()
    new_stamp = datetime(2026, 9, 4, 9, 0, tzinfo=bkk).timestamp()
    assert old_stamp != new_stamp

    seen: list[datetime] = []
    for epoch in (old_stamp, new_stamp):
        fake = _make_fake_ohlcv([_FakeBar(epoch, 10.0, 11.0, 9.0, 10.5, 1000.0)])
        monkeypatch.setattr(tvkit_client, "OHLCV", fake)
        rows = await tvkit_client.fetch_ohlcv(
            symbol="SET:PTT", timeframe="1d", cookies={"sessionid": "x"}, bars_count=1
        )
        seen.append(rows[0].ts)

    assert seen[0] == seen[1] == datetime(2026, 9, 4, tzinfo=UTC)


async def test_intraday_bars_keep_their_vendor_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only 1d is floored — flooring 5m would collapse a session onto one key."""
    epoch = datetime(2026, 9, 4, 6, 45, tzinfo=UTC).timestamp()
    fake = _make_fake_ohlcv([_FakeBar(epoch, 10.0, 11.0, 9.0, 10.5, 1000.0)])
    monkeypatch.setattr(tvkit_client, "OHLCV", fake)
    rows = await tvkit_client.fetch_ohlcv(
        symbol="SET:PTT", timeframe="5m", cookies={"sessionid": "x"}, bars_count=1
    )
    assert rows[0].ts == datetime(2026, 9, 4, 6, 45, tzinfo=UTC)
