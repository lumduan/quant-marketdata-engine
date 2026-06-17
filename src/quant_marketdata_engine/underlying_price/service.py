"""TFEX underlying-price service (read-through cache over the own Redis sidecar).

The underlying price is the **underlying instrument's** spot (for SET50 index
options/futures, the SET50 index), fetched via the ``settfex`` library — public
TFEX exchange data (no broker credentials, no tvkit cookie). The read path
resolves:

    Redis hot cache  →  single-flight'd settfex fetch  →  write-through

Unlike daily settlement, the underlying spot is intraday/live, so the cache TTL
is short (default 60 s). Cache reads and writes **degrade gracefully** — a Redis
miss or error logs a warning and behaves as a miss, so a live fetch still serves
when Redis is down. Every ``settfex`` failure is wrapped in
:class:`UnderlyingPriceFetchError`, carrying the upstream HTTP status when one is
known so the API layer can map 404 vs 502/503.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

import httpx
import redis.asyncio as aioredis

from src.quant_marketdata_engine.cache.single_flight import single_flight
from src.quant_marketdata_engine.underlying_price.errors import UnderlyingPriceFetchError
from src.quant_marketdata_engine.underlying_price.models import UnderlyingPriceQuote

logger = logging.getLogger(__name__)

_KEY_PREFIX = "mde:underlying-price"
_LOCK_PREFIX = "mde:underlying-price:lock"

# Decimal-or-null fields that round-trip through Redis JSON as decimal strings.
_DECIMAL_FIELDS = (
    "last",
    "prior",
    "high",
    "low",
    "change",
    "percent_change",
    "pe",
    "pbv",
)


def cache_key(symbol: str) -> str:
    """Build the Redis cache key for a symbol's underlying-price quote."""
    return f"{_KEY_PREFIX}:{symbol}"


def _quote_to_json(quote: UnderlyingPriceQuote) -> str:
    payload: dict[str, Any] = {
        "symbol": quote.symbol,
        "underlying_symbol": quote.underlying_symbol,
        "market_status": quote.market_status,
        "underlying_type": quote.underlying_type,
        "as_of": quote.as_of.isoformat(),
    }
    for field in _DECIMAL_FIELDS:
        value: Decimal | None = getattr(quote, field)
        payload[field] = None if value is None else str(value)
    return json.dumps(payload)


def _quote_from_json(raw: str | bytes) -> UnderlyingPriceQuote:
    data = json.loads(raw)
    fields: dict[str, Any] = {
        "symbol": data["symbol"],
        "underlying_symbol": data["underlying_symbol"],
        "market_status": data["market_status"],
        "underlying_type": data["underlying_type"],
        "as_of": data["as_of"],
    }
    for field in _DECIMAL_FIELDS:
        value = data.get(field)
        fields[field] = None if value is None else Decimal(value)
    return UnderlyingPriceQuote(**fields)


class UnderlyingPriceService:
    """Fetch + cache TFEX underlying-instrument spot prices via ``settfex``.

    Constructed with the engine's own Redis client (or ``None`` when Redis is
    unavailable — the cache then degrades to fetch-every-time).
    """

    def __init__(
        self,
        redis: aioredis.Redis | None,
        *,
        cache_ttl_seconds: int = 60,
    ) -> None:
        self._redis = redis
        self._ttl = cache_ttl_seconds

    async def fetch(self, symbol: str) -> UnderlyingPriceQuote:
        """Fetch a fresh underlying-price quote from TFEX via ``settfex`` (no cache).

        Raises:
            UnderlyingPriceFetchError: on any ``settfex``/transport failure. An
                HTTP status (e.g. 404 for an unknown series) is carried on the error.
        """
        # Import lazily so the heavy settfex import is paid only on a cold fetch
        # and the rest of the engine starts without it.
        from settfex.services.tfex.underlying_price import get_underlying_price

        logger.info("fetching TFEX underlying price for %s", symbol)
        try:
            stats = await get_underlying_price(symbol)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            logger.warning(
                "settfex underlying-price fetch for %s failed: HTTP %s", symbol, status_code
            )
            raise UnderlyingPriceFetchError(
                f"settfex fetch failed for {symbol}", status_code=status_code
            ) from exc
        except Exception as exc:
            logger.warning("settfex underlying-price fetch for %s failed: %s", symbol, exc)
            raise UnderlyingPriceFetchError(f"settfex fetch failed for {symbol}") from exc
        return UnderlyingPriceQuote.from_settfex(stats, symbol=symbol)

    async def get(self, symbol: str) -> UnderlyingPriceQuote:
        """Return a quote: Redis cache → single-flight fetch → cache.

        Raises:
            UnderlyingPriceFetchError: if a cold fetch is required and ``settfex``
                fails.
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

    async def _get_cached(self, symbol: str) -> UnderlyingPriceQuote | None:
        if self._redis is None:
            return None
        key = cache_key(symbol)
        try:
            raw = await self._redis.get(key)
        except Exception:
            logger.warning("underlying-price cache get failed for %s; treating as miss", key)
            return None
        if raw is None:
            return None
        try:
            return _quote_from_json(raw)
        except Exception:
            logger.warning("underlying-price cache decode failed for %s; treating as miss", key)
            return None

    async def _set_cached(self, quote: UnderlyingPriceQuote) -> None:
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
            logger.warning("underlying-price cache set failed for %s; serving uncached", key)
