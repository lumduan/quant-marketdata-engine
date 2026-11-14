"""TFEX daily-settlement service (read-through cache over the own Redis sidecar).

Settlement is **public** TFEX exchange data fetched via the ``settfex`` library
(no broker credentials, no tvkit cookie). The read path resolves:

    Redis hot cache  →  single-flight'd settfex fetch  →  write-through

Settlement is daily/stable, so the cache TTL is long (default 1 h). Cache reads
and writes **degrade gracefully** — a Redis miss or error logs a warning and
behaves as a miss, so a live fetch still serves when Redis is down. Every
``settfex`` failure is wrapped in :class:`SettlementFetchError`, carrying the
upstream HTTP status when one is known so the API layer can map 404 vs 502/503.
Measured against settfex 0.27.0 on 2026-11-14: an unknown series raises
``settfex.exceptions.SeriesNotFoundError`` with ``status_code=404``, and a real
series returns normally; ``tests/test_settlement_service.py`` drives that same
exception type, so this sentence fails with the test if it stops being true.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis

from src.quant_marketdata_engine.cache.single_flight import single_flight
from src.quant_marketdata_engine.settlement.errors import SettlementFetchError
from src.quant_marketdata_engine.settlement.models import SettlementQuote

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mde:settlement"
_LOCK_PREFIX = "mde:settlement:lock"

# Decimal-or-null fields that round-trip through Redis JSON as decimal strings.
_DECIMAL_FIELDS = (
    "settlement_price",
    "prior_settlement_price",
    "theoretical_price",
    "im",
    "mm",
)


def cache_key(symbol: str) -> str:
    """Build the Redis cache key for a symbol's settlement quote."""
    return f"{_KEY_PREFIX}:{symbol}"


def _quote_to_json(quote: SettlementQuote) -> str:
    payload: dict[str, Any] = {"symbol": quote.symbol, "as_of": quote.as_of.isoformat()}
    for field in _DECIMAL_FIELDS:
        value: Decimal | None = getattr(quote, field)
        payload[field] = None if value is None else str(value)
    return json.dumps(payload)


def _quote_from_json(raw: str | bytes) -> SettlementQuote:
    data = json.loads(raw)
    fields: dict[str, Any] = {
        "symbol": data["symbol"],
        "as_of": data["as_of"],
    }
    for field in _DECIMAL_FIELDS:
        value = data.get(field)
        fields[field] = None if value is None else Decimal(value)
    return SettlementQuote(**fields)


class SettlementService:
    """Fetch + cache TFEX daily settlements via ``settfex``.

    Constructed with the engine's own Redis client (or ``None`` when Redis is
    unavailable — the cache then degrades to fetch-every-time).
    """

    def __init__(
        self,
        redis: aioredis.Redis | None,
        *,
        cache_ttl_seconds: int = 3600,
    ) -> None:
        self._redis = redis
        self._ttl = cache_ttl_seconds

    async def fetch(self, symbol: str) -> SettlementQuote:
        """Fetch a fresh settlement quote from TFEX via ``settfex`` (no cache).

        Raises:
            SettlementFetchError: on any ``settfex``/transport failure.
                ``status_code`` carries settfex's own ``FetchError.status_code``
                (404 for an unknown series, verified live against 0.27.0), and is
                ``None`` for a transport/parse failure that never reached HTTP.
        """
        # Import lazily so the heavy settfex import is paid only on a cold fetch
        # and the rest of the engine starts without it.
        from settfex import exceptions as settfex_exc
        from settfex.services.tfex.trading_statistics import get_trading_statistics

        logger.info("fetching TFEX settlement for %s", symbol)
        try:
            stats = await get_trading_statistics(symbol)
        except settfex_exc.FetchError as exc:
            # settfex's OWN FetchError, never httpx's same-named class: settfex does not
            # use httpx at all, so `except httpx.HTTPStatusError` here was unreachable and
            # status_code was always None (TK-0655). FetchError is the base that carries
            # status_code, so this catches SeriesNotFoundError(404) and its siblings alike.
            status_code = exc.status_code
            logger.warning(
                "settfex settlement fetch for %s failed: %s status_code=%s",
                symbol,
                type(exc).__name__,
                status_code,
            )
            raise SettlementFetchError(
                f"settfex fetch failed for {symbol}", status_code=status_code
            ) from exc
        except Exception as exc:
            logger.warning("settfex settlement fetch for %s failed: %s", symbol, exc)
            raise SettlementFetchError(f"settfex fetch failed for {symbol}") from exc
        return SettlementQuote.from_settfex(stats, symbol=symbol)

    async def get(self, symbol: str) -> SettlementQuote:
        """Return a settlement quote: Redis cache → single-flight fetch → cache.

        Raises:
            SettlementFetchError: if a cold fetch is required and ``settfex`` fails.
        """
        cached = await self._get_cached(symbol)
        if cached is not None:
            return cached

        async with single_flight(self._redis, f"{_LOCK_PREFIX}:{symbol}", ttl_seconds=30):
            # Re-check after acquiring the lock — a concurrent flight may have
            # already populated the cache while we waited.
            cached = await self._get_cached(symbol)
            if cached is not None:
                return cached
            quote = await self.fetch(symbol)
            await self._set_cached(quote)
            return quote

    async def _get_cached(self, symbol: str) -> SettlementQuote | None:
        if self._redis is None:
            return None
        key = cache_key(symbol)
        try:
            raw = await self._redis.get(key)
        except Exception:
            logger.warning("settlement cache get failed for %s; treating as miss", key)
            return None
        if raw is None:
            return None
        try:
            return _quote_from_json(raw)
        except Exception:
            logger.warning("settlement cache decode failed for %s; treating as miss", key)
            return None

    async def _set_cached(self, quote: SettlementQuote) -> None:
        if self._redis is None:
            return
        key = cache_key(quote.symbol)
        try:
            payload = _quote_to_json(quote)
            if self._ttl > 0:
                await self._redis.set(key, payload, ex=self._ttl)
            else:
                await self._redis.set(key, payload)
        except Exception:
            logger.warning("settlement cache set failed for %s; serving uncached", key)
