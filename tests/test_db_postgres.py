"""Tests for the asyncpg pool lifecycle helpers."""

from __future__ import annotations

from typing import Any

import asyncpg
import pytest
from src.quant_marketdata_engine.db import postgres
from src.quant_marketdata_engine.db.errors import PoolNotInitializedError, RepositoryError

from tests._fakes import FakeConn, FakePool


async def test_get_pool_uninitialized_raises() -> None:
    with pytest.raises(PoolNotInitializedError):
        postgres.get_pool()


async def test_close_pool_noop_when_uninitialized() -> None:
    await postgres.close_pool()  # must not raise


async def test_create_get_close_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePool(FakeConn())

    async def _fake_create_pool(**_: Any) -> FakePool:
        return fake

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)
    created = await postgres.create_pool("dsn", min_size=1, max_size=3)
    assert created is fake
    # Second call returns the same pool (no re-create).
    assert await postgres.create_pool("dsn") is fake
    assert postgres.get_pool() is fake
    await postgres.close_pool()
    assert fake.closed is True


async def test_create_pool_failure_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(**_: Any) -> None:
        raise OSError("no db")

    monkeypatch.setattr(asyncpg, "create_pool", _boom)
    with pytest.raises(RepositoryError, match="failed to create"):
        await postgres.create_pool("dsn")


async def test_ping_true_and_false() -> None:
    assert await postgres.ping(FakePool(FakeConn())) is True  # type: ignore[arg-type]
    assert await postgres.ping(FakePool(FakeConn(raise_on={"execute"}))) is False  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# ensure_pool — the recovery path. See db/postgres.py's module docstring.
# ─────────────────────────────────────────────────────────────────────────────


async def test_ensure_pool_reopens_after_a_failed_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 THE 2026-09-10 REGRESSION. A lost startup race must NOT be permanent.

    The container started 0.324 s before Postgres, ``create_pool`` raised, the
    lifespan swallowed it, and the read API then served 503 for 33 h against a
    database that was healthy the whole time — because nothing ever retried.
    """
    fake = FakePool(FakeConn())
    db_up = {"value": False}

    async def _create_pool(**_: Any) -> FakePool:
        if not db_up["value"]:
            raise OSError("no db")
        return fake

    monkeypatch.setattr(asyncpg, "create_pool", _create_pool)

    # Startup, exactly as the lifespan does it: the failure is swallowed.
    with pytest.raises(RepositoryError):
        await postgres.create_pool("dsn")
    assert postgres._pool is None

    # A request arrives while the DB is still down — refused, not crashed.
    with pytest.raises(PoolNotInitializedError):
        await postgres.ensure_pool("dsn", cooldown_seconds=0)

    # Postgres finishes booting. The very next request must succeed, with no
    # container restart and no operator action.
    db_up["value"] = True
    assert await postgres.ensure_pool("dsn", cooldown_seconds=0) is fake
    assert postgres.get_pool() is fake


async def test_ensure_pool_cooldown_prevents_a_reconnect_storm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One connect attempt per cooldown window, not one per inbound request."""
    calls = {"n": 0}

    async def _boom(**_: Any) -> None:
        calls["n"] += 1
        raise OSError("no db")

    monkeypatch.setattr(asyncpg, "create_pool", _boom)
    for _ in range(5):
        with pytest.raises(PoolNotInitializedError):
            await postgres.ensure_pool("dsn", cooldown_seconds=60)
    assert calls["n"] == 1


async def test_ensure_pool_returns_the_open_pool_without_reconnecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path must not add a connect attempt to every request."""
    fake = FakePool(FakeConn())
    calls = {"n": 0}

    async def _create_pool(**_: Any) -> FakePool:
        calls["n"] += 1
        return fake

    monkeypatch.setattr(asyncpg, "create_pool", _create_pool)
    assert await postgres.ensure_pool("dsn") is fake
    assert await postgres.ensure_pool("dsn") is fake
    assert calls["n"] == 1


async def test_close_pool_clears_the_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deliberate close must not leave a stale cooldown blocking the reopen."""

    async def _boom(**_: Any) -> None:
        raise OSError("no db")

    monkeypatch.setattr(asyncpg, "create_pool", _boom)
    with pytest.raises(PoolNotInitializedError):
        await postgres.ensure_pool("dsn", cooldown_seconds=60)
    assert postgres._last_attempt is not None
    await postgres.close_pool()
    assert postgres._last_attempt is None
