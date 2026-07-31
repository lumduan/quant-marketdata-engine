"""Tests for the bulk daily refresh (no real DB / Redis / tvkit)."""

from __future__ import annotations

from typing import Any

import pytest
from src.quant_marketdata_engine.config.errors import CookieConfigError
from src.quant_marketdata_engine.config.settings import Settings
from src.quant_marketdata_engine.db.errors import RepositoryError
from src.quant_marketdata_engine.ingest import daily
from src.quant_marketdata_engine.ingest.daily import DailyIngestResult, run_daily_ingest
from src.quant_marketdata_engine.ingest.errors import IngestDisabledError, TvkitFetchError

COOKIE = '{"sessionid": "x"}'


def _owner_settings(**kw: Any) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None, public_mode=False, tvkit_auth_token=COOKIE, **kw
    )


def _result(attempted: int, succeeded: int, failed: int) -> DailyIngestResult:
    return DailyIngestResult(
        timeframe="1d",
        attempted=attempted,
        succeeded=succeeded,
        failed=failed,
        rows_written=0,
    )


def test_result_ok_semantics() -> None:
    # No symbols resolved is a misconfiguration, not a benign no-op.
    assert not _result(0, 0, 0).ok
    # Every symbol failing is a systemic fault (expired cookie, upstream down).
    assert not _result(5, 0, 5).ok
    # A partial failure is normal at 692 symbols and must still report success.
    assert _result(5, 4, 1).ok


async def test_public_mode_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def _never(**_kw: Any) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(daily, "ingest_ohlcv", _never)
    with pytest.raises(IngestDisabledError):
        await run_daily_ingest(
            settings=Settings(_env_file=None, public_mode=True),  # type: ignore[call-arg]
            pool=object(),  # type: ignore[arg-type]
            redis=None,
            min_interval=0.0,
            symbols=["SET:PTT"],
        )
    assert not called, "public mode must be rejected before any fetch"


async def test_missing_cookie_fails_fast() -> None:
    with pytest.raises(CookieConfigError):
        await run_daily_ingest(
            settings=Settings(_env_file=None, public_mode=False),  # type: ignore[call-arg]
            pool=object(),  # type: ignore[arg-type]
            redis=None,
            min_interval=0.0,
            symbols=["SET:PTT"],
        )


async def test_happy_path_sums_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    async def _fake(**kw: Any) -> int:
        seen.append(str(kw["symbol"]))
        assert kw["bars_count"] == 30
        return 3

    monkeypatch.setattr(daily, "ingest_ohlcv", _fake)
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
        symbols=["SET:A", "SET:B"],
        bars=30,
    )
    assert sorted(seen) == ["SET:A", "SET:B"]
    assert (result.attempted, result.succeeded, result.failed) == (2, 2, 0)
    assert result.rows_written == 6 and result.ok


async def test_per_symbol_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kw: Any) -> int:
        if kw["symbol"] == "SET:BAD":
            raise TvkitFetchError("upstream boom")
        return 2

    monkeypatch.setattr(daily, "ingest_ohlcv", _fake)
    monkeypatch.setattr(daily, "RETRY_BACKOFF_SECONDS", 0.0)
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
        symbols=["SET:GOOD", "SET:BAD"],
        retries=1,
    )
    assert result.failures == ["SET:BAD"]
    assert (result.succeeded, result.failed, result.rows_written) == (1, 1, 2)
    assert result.ok, "one bad symbol must not fail the whole run"


async def test_repository_failure_is_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake(**kw: Any) -> int:
        raise RepositoryError("upsert exploded")

    monkeypatch.setattr(daily, "ingest_ohlcv", _fake)
    monkeypatch.setattr(daily, "RETRY_BACKOFF_SECONDS", 0.0)
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
        symbols=["SET:A"],
        retries=0,
    )
    assert (result.succeeded, result.failed) == (0, 1) and not result.ok


async def test_retry_then_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    async def _flaky(**_kw: Any) -> int:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TvkitFetchError("transient")
        return 9

    monkeypatch.setattr(daily, "ingest_ohlcv", _flaky)
    monkeypatch.setattr(daily, "RETRY_BACKOFF_SECONDS", 0.0)
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
        symbols=["SET:FLAKY"],
        retries=2,
    )
    assert attempts == 3
    assert result.rows_written == 9 and result.succeeded == 1


async def test_symbols_default_to_store_and_limit_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_list(_pool: Any, *, timeframe: str) -> list[str]:
        assert timeframe == "1d"
        return ["SET:A", "SET:B", "SET:C"]

    async def _fake(**_kw: Any) -> int:
        return 1

    monkeypatch.setattr(daily, "list_tracked_symbols", _fake_list)
    monkeypatch.setattr(daily, "ingest_ohlcv", _fake)
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
        limit=2,
    )
    assert result.attempted == 2


async def test_empty_symbol_set_is_not_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(_pool: Any, *, timeframe: str) -> list[str]:
        return []

    monkeypatch.setattr(daily, "list_tracked_symbols", _empty)
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
    )
    assert result.attempted == 0 and not result.ok


async def test_concurrency_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    live = 0
    peak = 0

    async def _fake(**_kw: Any) -> int:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            import asyncio

            await asyncio.sleep(0)
        finally:
            live -= 1
        return 1

    monkeypatch.setattr(daily, "ingest_ohlcv", _fake)
    await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        min_interval=0.0,
        symbols=[f"SET:S{i}" for i in range(20)],
        concurrency=3,
    )
    assert peak <= 3, f"semaphore breached: peak={peak}"


async def test_pacer_enforces_minimum_interval() -> None:
    """The rate ceiling is what keeps a full-universe run under TradingView's limit."""
    import asyncio

    pacer = daily._Pacer(0.05)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(*(pacer.wait() for _ in range(4)))
    elapsed = loop.time() - started
    # 4 paced starts => at least 3 intervals of spacing.
    assert elapsed >= 0.15 - 0.01, f"pacer did not space starts: {elapsed:.3f}s"


async def test_pacer_disabled_is_a_noop() -> None:
    import asyncio

    pacer = daily._Pacer(0.0)
    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.gather(*(pacer.wait() for _ in range(50)))
    assert loop.time() - started < 0.05


async def test_daily_paces_fetch_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    """min_interval must throttle the real ingest loop, not just the helper."""
    import asyncio

    async def _fake(**_kw: Any) -> int:
        return 1

    monkeypatch.setattr(daily, "ingest_ohlcv", _fake)
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await run_daily_ingest(
        settings=_owner_settings(),
        pool=object(),  # type: ignore[arg-type]
        redis=None,
        symbols=[f"SET:S{i}" for i in range(4)],
        concurrency=4,
        min_interval=0.05,
    )
    assert result.succeeded == 4
    assert loop.time() - started >= 0.15 - 0.01
