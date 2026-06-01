"""Shared fixtures: reset module-level singletons between tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from src.quant_marketdata_engine.cache import redis_client
from src.quant_marketdata_engine.config import settings as settings_mod
from src.quant_marketdata_engine.db import postgres


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    """Clear module-global pool/redis/settings caches around each test."""
    postgres._pool = None
    redis_client._client = None
    settings_mod.get_settings.cache_clear()
    yield
    postgres._pool = None
    redis_client._client = None
    settings_mod.get_settings.cache_clear()
