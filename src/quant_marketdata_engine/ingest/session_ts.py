"""Canonical timestamps for daily bars.

🔴 WHY THIS EXISTS. The primary key of ``market_data.ohlcv`` is
``(symbol, timeframe, ts)``, so the vendor's wall-clock stamp is part of a bar's
identity. TradingView moves that stamp: measured 2026-09-11, SET daily bars were
stamped 09:55 Bangkok through 2026-09-07 and 09:00 from 2026-09-08. The daily
ingest re-fetches a 30-bar window, so the move rewrote the whole window at the
new stamp and **orphaned every old-stamp row** -- 69,762 duplicated symbol-days
and 111,193 extra rows across the store. Between moves the upsert behaves
correctly and creates nothing, which is why this looks dormant most days.

Flooring a daily bar to its session date makes the row's identity independent of
a stamp the vendor controls.

⚠️ **This deliberately does NOT apply to the parquet backfill path.** Seeded
``csm-backfill-div`` rows are dividend-adjusted and sit at 02:00Z; normalising
them too would make them collide with tvkit rows on the same key, and the upsert
would silently resolve a price disagreement -- 51 of 20,000 sampled overlapping
symbol-days differ -- in favour of whichever wrote last, while
``source = EXCLUDED.source`` relabelled the provenance. Operator decision,
2026-09-11: normalise the tvkit path only, to midnight UTC, so the two sources
can never share a key. See ``tests/test_ingest_backfill.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

#: The exchange whose calendar date defines a daily bar's session.
SESSION_TZ = ZoneInfo("Asia/Bangkok")

#: Only this timeframe is floored; intraday bars keep their true instant.
DAILY_TIMEFRAME = "1d"


def canonical_ts(ts: datetime, timeframe: str) -> datetime:
    """Return the storage timestamp for a bar.

    For ``1d`` bars this is midnight UTC of the bar's Bangkok session date, so
    two fetches of the same session agree on the primary key no matter what
    time-of-day the vendor stamped. Every other timeframe is returned unchanged.

    Args:
        ts: The vendor's bar-open instant. Must be timezone-aware.
        timeframe: The bar's timeframe (``1d`` / ``1h`` / ``5m``).

    Returns:
        A timezone-aware UTC datetime.

    Raises:
        ValueError: ``ts`` is naive, so its session date is undefined.
    """
    if ts.tzinfo is None:
        raise ValueError("canonical_ts requires a timezone-aware datetime")
    if timeframe != DAILY_TIMEFRAME:
        return ts
    session_date = ts.astimezone(SESSION_TZ).date()
    return datetime(session_date.year, session_date.month, session_date.day, tzinfo=UTC)
