"""FastAPI application factory + async lifespan.

Run with::

    uv run uvicorn src.quant_marketdata_engine.api.main:app --host 0.0.0.0 --port 8000

The lifespan eagerly opens the asyncpg pool and the own-Redis client and closes
them on shutdown. Startup is resilient: if a dependency is unreachable the app
still starts and ``/health`` reports ``degraded`` (so orchestrators get a signal
rather than a crash loop).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.quant_marketdata_engine.api.routes import router
from src.quant_marketdata_engine.cache.redis_client import close_redis, create_redis
from src.quant_marketdata_engine.config.settings import get_settings
from src.quant_marketdata_engine.db.postgres import close_pool, create_pool
from src.quant_marketdata_engine.logging_config import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Open/close the DB pool and Redis client around the app's lifetime."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "starting quant-marketdata-engine (public_mode=%s, cookie_present=%s)",
        settings.public_mode,
        settings.has_cookie,
    )
    try:
        await create_pool(
            settings.pg_dsn,
            min_size=settings.pg_pool_min_size,
            max_size=settings.pg_pool_max_size,
        )
    except Exception:
        logger.warning("startup: postgres pool unavailable; /health will report degraded")
    create_redis(settings.redis_url)
    try:
        yield
    finally:
        await close_redis()
        await close_pool()


def create_app() -> FastAPI:
    """Build the FastAPI app."""
    app = FastAPI(
        title="quant-marketdata-engine",
        version="0.1.0",
        summary="Canonical OHLCV read API + sole tvkit-cookie owner (gateway-proxied).",
        lifespan=lifespan,
    )
    app.include_router(router)
    return app


app = create_app()
