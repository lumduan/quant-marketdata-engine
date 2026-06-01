"""Export canonical OHLCV from the DB to columnar Parquet (ADR D3).

The Parquet snapshot is a **derived backtest cache** for heavy offline historical
scans — never a parallel source of truth. Prices are written as exact
``decimal128`` (not float) to preserve the money rule; ``ts`` is a UTC timestamp.
"""

from __future__ import annotations

import logging
from pathlib import Path

import asyncpg
import pyarrow as pa
import pyarrow.parquet as pq

from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.db.repositories import fetch_ohlcv, fetch_ohlcv_adjusted

logger = logging.getLogger(__name__)

_PRICE_TYPE = pa.decimal128(18, 6)
_VOLUME_TYPE = pa.decimal128(20, 4)

_SCHEMA = pa.schema(
    [
        pa.field("symbol", pa.string()),
        pa.field("timeframe", pa.string()),
        pa.field("ts", pa.timestamp("us", tz="UTC")),
        pa.field("open", _PRICE_TYPE),
        pa.field("high", _PRICE_TYPE),
        pa.field("low", _PRICE_TYPE),
        pa.field("close", _PRICE_TYPE),
        pa.field("volume", _VOLUME_TYPE),
        pa.field("open_interest", _VOLUME_TYPE),
        pa.field("source", pa.string()),
    ]
)


def bars_to_table(bars: list[OHLCVBarRow]) -> pa.Table:
    """Build a typed Arrow table (exact decimals) from bar rows."""
    return pa.table(
        {
            "symbol": [b.symbol for b in bars],
            "timeframe": [b.timeframe for b in bars],
            "ts": [b.ts for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "open_interest": [b.open_interest for b in bars],
            "source": [b.source for b in bars],
        },
        schema=_SCHEMA,
    )


async def export_ohlcv(
    pool: asyncpg.Pool,
    *,
    symbol: str,
    timeframe: str,
    out_path: Path,
    adjusted: bool = False,
    limit: int = 100_000,
) -> int:
    """Export ``(symbol, timeframe)`` bars to ``out_path`` as Parquet.

    Returns the number of bars written. Reads the adjust-on-read view when
    ``adjusted`` is true, else the raw base table.
    """
    fetch = fetch_ohlcv_adjusted if adjusted else fetch_ohlcv
    bars = await fetch(pool, symbol=symbol, timeframe=timeframe, limit=limit)
    table = bars_to_table(bars)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out_path)  # type: ignore[no-untyped-call]
    logger.info("exported %d bars to %s (adjusted=%s)", len(bars), out_path, adjusted)
    return len(bars)
