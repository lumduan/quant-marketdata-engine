"""Configuration-layer errors."""

from __future__ import annotations

from src.quant_marketdata_engine.errors import MarketDataEngineError


class ConfigError(MarketDataEngineError):
    """Base for configuration problems."""


class CookieConfigError(ConfigError):
    """The tvkit cookie is missing or malformed.

    The offending value is never included in the message.
    """
