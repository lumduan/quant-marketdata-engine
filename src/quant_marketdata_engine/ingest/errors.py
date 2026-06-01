"""Ingest-layer errors."""

from __future__ import annotations

from src.quant_marketdata_engine.errors import MarketDataEngineError


class IngestError(MarketDataEngineError):
    """Base for ingest-side problems."""


class IngestDisabledError(IngestError):
    """Ingest was attempted while the service is in public (read-only) mode."""


class TvkitFetchError(IngestError):
    """A tvkit/TradingView fetch failed (network, rate limit, session expiry).

    The tvkit cookie is never included in the message.
    """
