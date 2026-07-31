"""Tests for the ingest CLI (deps monkeypatched — no real DB/Redis)."""

from __future__ import annotations

import argparse
from datetime import UTC
from typing import Any

import pytest
from src.quant_marketdata_engine.ingest import cli
from src.quant_marketdata_engine.ingest.daily import DailyIngestResult


def test_parse_ts_variants() -> None:
    assert cli._parse_ts(None) is None
    naive = cli._parse_ts("2026-05-29T00:00:00")
    assert naive is not None and naive.tzinfo == UTC
    aware = cli._parse_ts("2026-05-29T07:00:00+07:00")
    assert aware is not None and aware.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_build_parser_requires_command() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([])


def _patch_io(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(cli, "create_pool", _noop)
    monkeypatch.setattr(cli, "create_redis", lambda *a, **k: None)
    monkeypatch.setattr(cli, "get_pool", lambda: object())
    monkeypatch.setattr(cli, "close_redis", _noop)
    monkeypatch.setattr(cli, "close_pool", _noop)


async def test_run_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    seen: dict[str, Any] = {}

    async def _fake_ingest(**kw: Any) -> int:
        seen.update(kw)
        return 7

    monkeypatch.setattr(cli, "ingest_ohlcv", _fake_ingest)
    from src.quant_marketdata_engine.config.settings import Settings

    args = argparse.Namespace(
        command="fetch", symbol="SET:PTT", timeframe="1d", bars=10, start=None, end=None
    )
    n = await cli._run(args, Settings(_env_file=None, public_mode=False))  # type: ignore[call-arg]
    assert n == 7
    assert seen["symbol"] == "SET:PTT"


async def test_run_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)

    async def _fake_backfill(_pool: Any, _dir: Any, **kw: Any) -> int:
        return 3

    monkeypatch.setattr(cli, "backfill_from_dir", _fake_backfill)
    from src.quant_marketdata_engine.config.settings import Settings

    args = argparse.Namespace(command="backfill", dir="/tmp/x", timeframe="1d", limit_files=None)
    n = await cli._run(args, Settings(_env_file=None))  # type: ignore[call-arg]
    assert n == 3


async def test_run_daily_returns_rows_when_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    seen: dict[str, Any] = {}

    async def _fake_daily(**kw: Any) -> Any:
        seen.update(kw)
        return DailyIngestResult(
            timeframe="1d", attempted=3, succeeded=3, failed=0, rows_written=12
        )

    monkeypatch.setattr(cli, "run_daily_ingest", _fake_daily)
    from src.quant_marketdata_engine.config.settings import Settings

    args = argparse.Namespace(
        command="daily",
        timeframe="1d",
        bars=30,
        symbols="SET:A,SET:B",
        symbols_file=None,
        concurrency=4,
        retries=2,
        limit=None,
        min_interval=0.0,
    )
    n = await cli._run(args, Settings(_env_file=None, public_mode=False))  # type: ignore[call-arg]
    assert n == 12
    assert seen["symbols"] == ["SET:A", "SET:B"]


async def test_run_daily_signals_failure_with_negative(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run where every symbol failed must surface to cron as a non-zero exit."""
    _patch_io(monkeypatch)

    async def _fake_daily(**_kw: Any) -> Any:
        return DailyIngestResult(timeframe="1d", attempted=2, succeeded=0, failed=2, rows_written=0)

    monkeypatch.setattr(cli, "run_daily_ingest", _fake_daily)
    from src.quant_marketdata_engine.config.settings import Settings

    args = argparse.Namespace(
        command="daily",
        timeframe="1d",
        bars=30,
        symbols=None,
        symbols_file=None,
        concurrency=4,
        retries=2,
        limit=None,
        min_interval=0.0,
    )
    n = await cli._run(args, Settings(_env_file=None, public_mode=False))  # type: ignore[call-arg]
    assert n < 0


def test_resolve_symbols_from_file(tmp_path: Any) -> None:
    path = tmp_path / "syms.txt"
    path.write_text("# a comment\nSET:AAA\n\n  SET:BBB  \n", encoding="utf-8")
    args = argparse.Namespace(symbols=None, symbols_file=str(path))
    assert cli._resolve_symbols(args) == ["SET:AAA", "SET:BBB"]


def test_resolve_symbols_none_by_default() -> None:
    assert cli._resolve_symbols(argparse.Namespace(symbols=None, symbols_file=None)) is None


def test_daily_parser_defaults() -> None:
    args = cli.build_parser().parse_args(["daily"])
    assert args.command == "daily" and args.timeframe == "1d" and args.bars > 0


def test_main_invokes_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(_args: Any, _settings: Any) -> int:
        return 5

    monkeypatch.setattr(cli, "_run", _fake_run)
    rc = cli.main(["fetch", "--symbol", "X", "--timeframe", "1d"])
    assert rc == 5


async def test_run_rename_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_io(monkeypatch)
    seen: dict[str, Any] = {}

    async def _fake_rename(_pool: Any, **kw: Any) -> dict[str, int]:
        seen.update(kw)
        return {"ohlcv": 5040, "corporate_actions": 0, "universe_membership": 0}

    monkeypatch.setattr(cli, "rename_symbol", _fake_rename)
    from src.quant_marketdata_engine.config.settings import Settings

    args = argparse.Namespace(
        command="rename-symbol", old_symbol="SET:BANPU", new_symbol="SET:BANPUU"
    )
    n = await cli._run(args, Settings(_env_file=None))  # type: ignore[call-arg]
    assert n == 5040
    assert seen == {"old_symbol": "SET:BANPU", "new_symbol": "SET:BANPUU"}


def test_rename_symbol_parser() -> None:
    args = cli.build_parser().parse_args(
        ["rename-symbol", "--from", "SET:BANPU", "--to", "SET:BANPUU"]
    )
    assert (args.command, args.old_symbol, args.new_symbol) == (
        "rename-symbol",
        "SET:BANPU",
        "SET:BANPUU",
    )
