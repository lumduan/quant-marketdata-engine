"""Tests for the ingest CLI (deps monkeypatched — no real DB/Redis)."""

from __future__ import annotations

import argparse
from datetime import UTC
from typing import Any

import pytest
from src.quant_marketdata_engine.ingest import cli


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


def test_main_invokes_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(_args: Any, _settings: Any) -> int:
        return 5

    monkeypatch.setattr(cli, "_run", _fake_run)
    rc = cli.main(["fetch", "--symbol", "X", "--timeframe", "1d"])
    assert rc == 5
