"""Read-API + owner-mode admin routes.

``/ohlcv`` and ``/ohlcv/adjusted`` resolve hot/warm: Redis hot-window cache →
TimescaleDB → write-through. (Cold-path auto-fetch-on-miss is deferred; ingest is
a separate path.) All read params are validated/whitelisted at the boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

import asyncpg
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.quant_marketdata_engine.api.deps import (
    get_pool_dep,
    get_redis_dep,
    get_settings_dep,
    require_api_key,
    require_owner_mode,
)
from src.quant_marketdata_engine.api.schemas import (
    HealthResponse,
    IngestRequest,
    IngestResponse,
    OHLCVBar,
    OHLCVResponse,
    Timeframe,
    UniverseResponse,
)
from src.quant_marketdata_engine.cache import ohlcv_cache
from src.quant_marketdata_engine.cache.redis_client import get_redis
from src.quant_marketdata_engine.cache.redis_client import ping as redis_ping
from src.quant_marketdata_engine.config.settings import Settings
from src.quant_marketdata_engine.db.models import OHLCVBarRow
from src.quant_marketdata_engine.db.postgres import get_pool
from src.quant_marketdata_engine.db.postgres import ping as pg_ping
from src.quant_marketdata_engine.db.repositories import (
    fetch_ohlcv,
    fetch_ohlcv_adjusted,
    fetch_universe,
)
from src.quant_marketdata_engine.ingest.errors import IngestError, TvkitFetchError
from src.quant_marketdata_engine.ingest.service import ingest_ohlcv

logger = logging.getLogger(__name__)

router = APIRouter()

_FetchFn = Callable[..., Awaitable[list[OHLCVBarRow]]]


def _to_bar(row: OHLCVBarRow) -> OHLCVBar:
    return OHLCVBar(
        ts=row.ts,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        volume=row.volume,
        open_interest=row.open_interest,
    )


def _validate_range(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start must be <= end",
        )


@router.get("/health", response_model=HealthResponse, summary="Engine readiness")
async def health(settings: Settings = Depends(get_settings_dep)) -> HealthResponse:
    """Report DB + Redis reachability and tvkit-cookie presence (never the value)."""
    db_ok = False
    try:
        db_ok = await pg_ping(get_pool())
    except Exception:
        logger.warning("health: postgres pool unavailable", exc_info=True)
    redis_ok = False
    client = get_redis()
    if client is not None:
        redis_ok = await redis_ping(client)
    status_label = "ok" if db_ok else "degraded"
    return HealthResponse(
        status=status_label,
        db=db_ok,
        redis=redis_ok,
        cookie_present=settings.has_cookie,
    )


async def _read(
    *,
    fetch: _FetchFn,
    adjusted: bool,
    symbol: str,
    timeframe: Timeframe,
    start: datetime | None,
    end: datetime | None,
    limit: int,
    pool: asyncpg.Pool,
    redis: aioredis.Redis | None,
    settings: Settings,
) -> OHLCVResponse:
    _validate_range(start, end)
    key = ohlcv_cache.make_key(
        symbol=symbol, timeframe=timeframe, adjusted=adjusted, start=start, end=end, limit=limit
    )
    cached = await ohlcv_cache.get_cached_bars(redis, key)
    if cached is not None:
        rows = cached
    else:
        rows = await fetch(
            pool, symbol=symbol, timeframe=timeframe, start=start, end=end, limit=limit
        )
        await ohlcv_cache.set_cached_bars(redis, key, rows, settings.cache_ttl_seconds)
    return OHLCVResponse(
        symbol=symbol, timeframe=timeframe, adjusted=adjusted, bars=[_to_bar(r) for r in rows]
    )


@router.get(
    "/ohlcv",
    response_model=OHLCVResponse,
    summary="Raw OHLCV bars",
    dependencies=[Depends(require_api_key)],
)
async def get_ohlcv(
    symbol: str = Query(min_length=1, max_length=64),
    timeframe: Timeframe = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=50000),
    pool: asyncpg.Pool = Depends(get_pool_dep),
    redis: aioredis.Redis | None = Depends(get_redis_dep),
    settings: Settings = Depends(get_settings_dep),
) -> OHLCVResponse:
    """Return raw (split-adjusted base) bars; hot/warm resolution."""
    return await _read(
        fetch=fetch_ohlcv,
        adjusted=False,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
        pool=pool,
        redis=redis,
        settings=settings,
    )


@router.get(
    "/ohlcv/adjusted",
    response_model=OHLCVResponse,
    summary="Adjust-on-read OHLCV bars",
    dependencies=[Depends(require_api_key)],
)
async def get_ohlcv_adjusted(
    symbol: str = Query(min_length=1, max_length=64),
    timeframe: Timeframe = Query(...),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=50000),
    pool: asyncpg.Pool = Depends(get_pool_dep),
    redis: aioredis.Redis | None = Depends(get_redis_dep),
    settings: Settings = Depends(get_settings_dep),
) -> OHLCVResponse:
    """Return dividend/split adjust-on-read bars (futures-roll parity is Phase 4)."""
    return await _read(
        fetch=fetch_ohlcv_adjusted,
        adjusted=True,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        limit=limit,
        pool=pool,
        redis=redis,
        settings=settings,
    )


@router.get(
    "/universe",
    response_model=UniverseResponse,
    summary="Point-in-time index constituents",
    dependencies=[Depends(require_api_key)],
)
async def get_universe(
    as_of: date = Query(...),
    index_name: str = Query(default="SET", min_length=1, max_length=32),
    pool: asyncpg.Pool = Depends(get_pool_dep),
) -> UniverseResponse:
    """Return as-of dated constituents (latest snapshot on or before ``as_of``)."""
    resolved, symbols = await fetch_universe(pool, as_of=as_of, index_name=index_name)
    return UniverseResponse(as_of=resolved, index_name=index_name, symbols=symbols)


@router.post(
    "/admin/ingest",
    response_model=IngestResponse,
    summary="Owner-mode tvkit ingest",
    dependencies=[Depends(require_api_key), Depends(require_owner_mode)],
)
async def admin_ingest(
    body: IngestRequest,
    pool: asyncpg.Pool = Depends(get_pool_dep),
    redis: aioredis.Redis | None = Depends(get_redis_dep),
    settings: Settings = Depends(get_settings_dep),
) -> IngestResponse:
    """Fetch from tvkit and idempotently upsert (owner mode + API key required)."""
    try:
        written = await ingest_ohlcv(
            settings=settings,
            pool=pool,
            redis=redis,
            symbol=body.symbol,
            timeframe=body.timeframe,
            bars_count=body.bars,
            start=body.start,
            end=body.end,
        )
    except TvkitFetchError as exc:
        logger.warning("admin ingest upstream failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="upstream tvkit fetch failed"
        ) from exc
    except IngestError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return IngestResponse(symbol=body.symbol, timeframe=body.timeframe, rows_written=written)
