"""Cache-layer errors."""

from __future__ import annotations

from src.quant_marketdata_engine.errors import MarketDataEngineError


class CacheError(MarketDataEngineError):
    """Base for Redis cache problems (callers usually degrade rather than raise)."""
