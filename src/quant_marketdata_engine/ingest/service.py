"""Ingest orchestration: fetch → idempotent upsert → cache invalidation.

This is the shared core behind both the ingest CLI and the owner-mode
``POST /admin/ingest`` endpoint. It refuses to run in public mode, single-flights
the fetch on ``(symbol, timeframe, range)`` so concurrent callers hit TradingView
once, and relies on idempotent ``ON CONFLICT`` upserts so re-runs are safe.
"""

from __future__ import annotations

import logging
from datetime import datetime

import asyncpg
import redis.asyncio as aioredis

from src.quant_marketdata_engine.cache import ohlcv_cache, single_flight
from src.quant_marketdata_engine.config.settings import Settings
from src.quant_marketdata_engine.db.repositories import upsert_ohlcv
from src.quant_marketdata_engine.ingest import tvkit_client
from src.quant_marketdata_engine.ingest.errors import IngestDisabledError

logger = logging.getLogger(__name__)


def _range_key(bars_count: int | None, start: datetime | None, end: datetime | None) -> str:
    start_s = start.isoformat() if start is not None else "-"
    end_s = end.isoformat() if end is not None else "-"
    return f"{bars_count if bars_count is not None else '-'}:{start_s}:{end_s}"


async def ingest_ohlcv(
    *,
    settings: Settings,
    pool: asyncpg.Pool,
    redis: aioredis.Redis | None,
    symbol: str,
    timeframe: str,
    bars_count: int | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> int:
    """Fetch and upsert raw bars for ``(symbol, timeframe)``. Returns rows written.

    Raises:
        IngestDisabledError: if the service is in public (read-only) mode.
        CookieConfigError: if the tvkit cookie is missing/malformed.
        TvkitFetchError: on upstream fetch failure.
        RepositoryError: on upsert failure.
    """
    if settings.public_mode:
        raise IngestDisabledError(
            "ingest is disabled in public mode (set MARKETDATA_ENGINE_PUBLIC_MODE=false)"
        )
    # Validates presence + shape; raises CookieConfigError. Never logged.
    cookies = settings.tvkit_cookies()

    key = single_flight.lock_key(
        symbol=symbol,
        timeframe=timeframe,
        range_key=_range_key(bars_count, start, end),
    )
    async with single_flight.single_flight(redis, key) as acquired:
        if not acquired:
            logger.info("ingest skipped (in-flight) symbol=%s timeframe=%s", symbol, timeframe)
            return 0
        bars = await tvkit_client.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            cookies=cookies,
            bars_count=bars_count,
            start=start,
            end=end,
        )
        written = await upsert_ohlcv(pool, bars)

    await ohlcv_cache.invalidate(redis, symbol=symbol, timeframe=timeframe)
    logger.info("ingest complete symbol=%s timeframe=%s rows=%d", symbol, timeframe, written)
    return written
