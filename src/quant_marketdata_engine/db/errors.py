"""Database-layer errors."""

from __future__ import annotations

from src.quant_marketdata_engine.errors import MarketDataEngineError


class DbError(MarketDataEngineError):
    """Base for database problems."""


class PoolNotInitializedError(DbError):
    """``get_pool`` was called before ``create_pool``."""


class RepositoryError(DbError):
    """An asyncpg operation failed; wraps the driver exception."""
