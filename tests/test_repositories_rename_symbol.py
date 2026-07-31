"""Tests for ``rename_symbol`` — the SET re-ticker path (no real DB)."""

from __future__ import annotations

from types import TracebackType
from typing import Any

import pytest
from src.quant_marketdata_engine.db.errors import RepositoryError
from src.quant_marketdata_engine.db.repositories import _SYMBOL_KEYED_TABLES, rename_symbol


class _FakeConn:
    """Minimal asyncpg connection double recording the SQL it is asked to run."""

    def __init__(self, collisions: dict[str, int] | None = None, updated: int = 3) -> None:
        self._collisions = collisions or {}
        self._updated = updated
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.transaction_entered = False

    def transaction(self) -> _FakeConn:
        return self

    async def __aenter__(self) -> _FakeConn:
        self.transaction_entered = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def fetchval(self, sql: str, *args: Any) -> int:
        for table in self._collisions:
            if f"market_data.{table} o" in sql:
                return self._collisions[table]
        return 0

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return f"UPDATE {self._updated}"


class _FakePool:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def acquire(self) -> _FakePool:
        return self

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


async def test_moves_every_symbol_keyed_table() -> None:
    """ohlcv alone is not enough — orphaned corporate actions silently break adjust-on-read."""
    conn = _FakeConn(updated=5)
    moved = await rename_symbol(
        _FakePool(conn),  # type: ignore[arg-type]
        old_symbol="SET:BANPU",
        new_symbol="SET:BANPUU",
    )
    assert set(moved) == {name for name, _ in _SYMBOL_KEYED_TABLES}
    assert "corporate_actions" in moved, "a rename that skips corporate actions corrupts adjusted"
    assert all(v == 5 for v in moved.values())
    assert len(conn.executed) == len(_SYMBOL_KEYED_TABLES)
    for sql, args in conn.executed:
        assert sql.startswith("UPDATE market_data.")
        assert args == ("SET:BANPU", "SET:BANPUU")


async def test_refuses_on_collision_and_moves_nothing() -> None:
    conn = _FakeConn(collisions={"ohlcv": 4})
    with pytest.raises(RepositoryError, match="rename_symbol refused"):
        await rename_symbol(
            _FakePool(conn),  # type: ignore[arg-type]
            old_symbol="SET:BANPU",
            new_symbol="SET:BANPUU",
        )
    assert conn.executed == [], "a refused rename must not half-apply"


async def test_collision_in_a_later_table_still_blocks_all() -> None:
    """Collisions are checked for every table before any UPDATE runs."""
    conn = _FakeConn(collisions={"universe_membership": 1})
    with pytest.raises(RepositoryError, match="universe_membership"):
        await rename_symbol(
            _FakePool(conn),  # type: ignore[arg-type]
            old_symbol="SET:A",
            new_symbol="SET:B",
        )
    assert conn.executed == []


async def test_identical_symbols_rejected() -> None:
    conn = _FakeConn()
    with pytest.raises(RepositoryError, match="identical"):
        await rename_symbol(
            _FakePool(conn),  # type: ignore[arg-type]
            old_symbol="SET:X",
            new_symbol="SET:X",
        )
    assert conn.executed == []


async def test_sql_failure_wrapped() -> None:
    class _Boom(_FakeConn):
        async def execute(self, sql: str, *args: Any) -> str:
            raise RuntimeError("connection reset")

    with pytest.raises(RepositoryError, match="rename_symbol failed"):
        await rename_symbol(
            _FakePool(_Boom()),  # type: ignore[arg-type]
            old_symbol="SET:A",
            new_symbol="SET:B",
        )
