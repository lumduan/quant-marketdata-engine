"""Shared in-memory test doubles for asyncpg and redis (no live services)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


class FakeConn:
    """A stand-in asyncpg connection that records calls and returns canned data."""

    def __init__(
        self,
        *,
        fetch_result: Sequence[dict[str, Any]] | None = None,
        fetchval_result: Any = None,
        raise_on: set[str] | None = None,
    ) -> None:
        self.fetch_result = list(fetch_result or [])
        self.fetchval_result = fetchval_result
        self.raise_on = raise_on or set()
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []

    def _maybe_raise(self, name: str) -> None:
        if name in self.raise_on:
            raise RuntimeError(f"fake {name} failure")

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args))
        self._maybe_raise("execute")
        return "EXECUTE 1"

    async def executemany(self, sql: str, args: Any) -> None:
        self.calls.append(("executemany", sql, tuple(args)))
        self._maybe_raise("executemany")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append(("fetch", sql, args))
        self._maybe_raise("fetch")
        return self.fetch_result

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.calls.append(("fetchval", sql, args))
        self._maybe_raise("fetchval")
        return self.fetchval_result


class _AcquireCM:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> FakeConn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class FakePool:
    """A stand-in asyncpg pool wrapping a single :class:`FakeConn`."""

    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn
        self.closed = False

    def acquire(self) -> _AcquireCM:
        return _AcquireCM(self.conn)

    async def close(self) -> None:
        self.closed = True


class FakeRedis:
    """A minimal in-memory async Redis double covering the ops the engine uses."""

    def __init__(self, *, fail: bool = False) -> None:
        self.store: dict[str, str] = {}
        self.fail = fail
        self.deleted: list[str] = []
        self.evals: list[str] = []
        self.closed = False

    async def get(self, key: str) -> str | None:
        if self.fail:
            raise RuntimeError("fake get failure")
        return self.store.get(key)

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if self.fail:
            raise RuntimeError("fake set failure")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key: str) -> int:
        self.deleted.append(key)
        self.store.pop(key, None)
        return 1

    async def scan_iter(self, match: str | None = None) -> AsyncIterator[str]:
        if self.fail:
            raise RuntimeError("fake scan failure")
        for key in list(self.store):
            yield key

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> int:
        if self.fail:
            raise RuntimeError("fake eval failure")
        self.evals.append(script)
        return 1

    async def ping(self) -> bool:
        if self.fail:
            raise RuntimeError("fake ping failure")
        return True

    async def aclose(self) -> None:
        self.closed = True


def make_bar_record(
    *,
    symbol: str = "SET:PTT",
    timeframe: str = "1d",
    ts: datetime | None = None,
    open_: str = "10.000000",
    high: str = "11.000000",
    low: str = "9.000000",
    close: str = "10.500000",
    volume: str = "1000.0000",
    open_interest: str | None = None,
) -> dict[str, Any]:
    """Build a DB-row-shaped dict matching ``OHLCVBarRow`` fields."""
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ts": ts or datetime(2026, 5, 29, tzinfo=UTC),
        "open": Decimal(open_),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal(volume),
        "open_interest": None if open_interest is None else Decimal(open_interest),
        "source": "tvkit",
        "ingested_at": datetime(2026, 5, 30, tzinfo=UTC),
    }
