"""Hot-window OHLCV cache (write-through) over the own Redis sidecar.

Bars are serialised JSON-safely (``Decimal`` → string, ``ts`` → ISO-8601) so the
money rule is preserved on the wire and on reload. Every operation **degrades
gracefully**: a Redis miss or error logs a warning and behaves as a cache miss,
so the read path still serves from the DB when Redis is down.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import redis.asyncio as aioredis

from src.quant_marketdata_engine.db.models import OHLCVBarRow

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mde:ohlcv"


def make_key(
    *,
    symbol: str,
    timeframe: str,
    adjusted: bool,
    start: datetime | None,
    end: datetime | None,
    limit: int,
) -> str:
    """Build a stable cache key for a read request."""
    start_s = start.isoformat() if start is not None else "-"
    end_s = end.isoformat() if end is not None else "-"
    variant = "adj" if adjusted else "raw"
    return f"{_KEY_PREFIX}:{variant}:{symbol}:{timeframe}:{start_s}:{end_s}:{limit}"


def _bar_to_jsonable(bar: OHLCVBarRow) -> dict[str, object]:
    return {
        "symbol": bar.symbol,
        "timeframe": bar.timeframe,
        "ts": bar.ts.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": str(bar.volume),
        "open_interest": None if bar.open_interest is None else str(bar.open_interest),
        "source": bar.source,
        "ingested_at": bar.ingested_at.isoformat() if bar.ingested_at else None,
    }


async def get_cached_bars(client: aioredis.Redis | None, key: str) -> list[OHLCVBarRow] | None:
    """Return cached bars for ``key``, or ``None`` on miss / error / no client."""
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception:
        logger.warning("cache get failed for %s; treating as miss", key, exc_info=True)
        return None
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return [OHLCVBarRow(**item) for item in payload]
    except Exception:
        logger.warning("cache decode failed for %s; treating as miss", key, exc_info=True)
        return None


async def set_cached_bars(
    client: aioredis.Redis | None,
    key: str,
    bars: list[OHLCVBarRow],
    ttl_seconds: int,
) -> None:
    """Write-through ``bars`` under ``key`` with ``ttl_seconds`` (best-effort)."""
    if client is None:
        return
    try:
        payload = json.dumps([_bar_to_jsonable(b) for b in bars])
        if ttl_seconds > 0:
            await client.set(key, payload, ex=ttl_seconds)
        else:
            await client.set(key, payload)
    except Exception:
        logger.warning("cache set failed for %s; serving uncached", key, exc_info=True)


async def invalidate(client: aioredis.Redis | None, *, symbol: str, timeframe: str) -> int:
    """Best-effort delete of cached read keys for ``(symbol, timeframe)``.

    Called after an ingest so the next read reflects freshly upserted bars.
    Returns the number of keys removed (0 on no client / error).
    """
    if client is None:
        return 0
    pattern = f"{_KEY_PREFIX}:*:{symbol}:{timeframe}:*"
    removed = 0
    try:
        async for found in client.scan_iter(match=pattern):
            await client.delete(found)
            removed += 1
    except Exception:
        logger.warning("cache invalidate failed for %s/%s", symbol, timeframe, exc_info=True)
    return removed
