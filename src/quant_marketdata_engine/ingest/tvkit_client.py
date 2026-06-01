"""Thin async wrapper around tvkit — the SOLE holder of the tvkit cookie.

This module is the only place ``TVKIT_AUTH_TOKEN`` is turned into a live
TradingView session. The cookie dict is passed to ``tvkit``'s ``OHLCV`` client
and **never logged**. Bars are stored RAW (split-adjusted, per ADR D2 — dividend
adjustment is applied on read), so we request ``Adjustment.SPLITS``.

The live network call cannot run in CI (no cookie), so tests monkeypatch the
module-level ``OHLCV`` reference; the mapping logic below is exercised directly.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from tvkit.api.chart.models.adjustment import Adjustment
from tvkit.api.chart.ohlcv import OHLCV

from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.ingest.errors import TvkitFetchError

logger = logging.getLogger(__name__)

# Our read-contract timeframe → TradingView resolution code.
_INTERVAL_BY_TIMEFRAME: dict[str, str] = {"1d": "1D", "1h": "60", "5m": "5"}


def _to_decimal(value: object) -> Decimal:
    """Convert a tvkit float field to ``Decimal`` without binary-float noise."""
    return Decimal(str(value))


def _bar_from_tvkit(raw: object, *, symbol: str, timeframe: str) -> OHLCVBarRow:
    """Map a tvkit ``OHLCVBar`` to our :class:`OHLCVBarRow` (UTC, Decimal)."""
    ts = datetime.fromtimestamp(float(raw.timestamp), tz=UTC)  # type: ignore[attr-defined]
    return OHLCVBarRow(
        symbol=symbol,
        timeframe=timeframe,
        ts=ts,
        open=_to_decimal(raw.open),  # type: ignore[attr-defined]
        high=_to_decimal(raw.high),  # type: ignore[attr-defined]
        low=_to_decimal(raw.low),  # type: ignore[attr-defined]
        close=_to_decimal(raw.close),  # type: ignore[attr-defined]
        volume=_to_decimal(raw.volume),  # type: ignore[attr-defined]
        open_interest=None,
        source="tvkit",
    )


async def fetch_ohlcv(
    *,
    symbol: str,
    timeframe: str,
    cookies: dict[str, str],
    bars_count: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[OHLCVBarRow]:
    """Fetch raw bars for ``(symbol, timeframe)`` from TradingView via tvkit.

    Args:
        symbol: TradingView exchange symbol (e.g. ``"TFEX:S501!"``, ``"SET:PTT"``).
        timeframe: One of ``1d`` / ``1h`` / ``5m``.
        cookies: Parsed tvkit cookie dict (sole credential — never logged).
        bars_count: Optional bar-depth request (premium accounts allow >5000).
        start / end: Optional UTC window for ``get_historical_ohlcv``.

    Raises:
        TvkitFetchError: on any upstream/mapping failure.
    """
    interval = _INTERVAL_BY_TIMEFRAME.get(timeframe)
    if interval is None:
        raise TvkitFetchError(f"unsupported timeframe for tvkit fetch: {timeframe!r}")
    logger.info(
        "tvkit fetch symbol=%s timeframe=%s bars=%s start=%s end=%s",
        symbol,
        timeframe,
        bars_count,
        start,
        end,
    )
    try:
        async with OHLCV(cookies=cookies) as client:
            raw_bars = await client.get_historical_ohlcv(
                symbol,
                interval=interval,
                bars_count=bars_count,
                start=start,
                end=end,
                adjustment=Adjustment.SPLITS,
            )
        bars = [_bar_from_tvkit(b, symbol=symbol, timeframe=timeframe) for b in raw_bars]
    except Exception as exc:
        # Never echo the cookie; only the symbol/timeframe context.
        raise TvkitFetchError(f"tvkit fetch failed for {symbol!r} {timeframe!r}: {exc}") from exc
    logger.info("tvkit fetch returned %d bars for %s %s", len(bars), symbol, timeframe)
    return bars
