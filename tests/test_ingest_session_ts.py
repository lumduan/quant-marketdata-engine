"""Daily bars are keyed by session date, not by the vendor's wall-clock stamp.

The primary key of ``market_data.ohlcv`` is ``(symbol, timeframe, ts)``, so the
stamp TradingView happens to put on a bar is part of that bar's identity. When
the vendor moves it, a re-fetch of the same session writes a SECOND row instead
of updating the first.

Measured 2026-09-11 on the live store: SET daily bars carried 09:55 Bangkok
through bar-date 2026-09-07 and 09:00 from 2026-09-08, and every bar-date in the
overlap window holds exactly two rows — 69,762 duplicated symbol-days,
111,193 extra rows. Between stamp moves the upsert is well-behaved and creates
nothing, which is why this is invisible on an ordinary day and why an
"is the next ingest clean?" check cannot detect it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from src.quant_marketdata_engine.ingest.session_ts import canonical_ts

BKK = timezone(timedelta(hours=7))


def test_two_stamps_for_one_session_collapse_to_one_key() -> None:
    """🔴 THE DISCRIMINATING TEST. Ingesting a session twice must yield ONE row.

    These are the two stamps actually observed either side of the 2026-09-08
    vendor change. Under the old behaviour they are different primary keys and
    the store grows a duplicate; under the fix they are the same key and the
    upsert updates in place.
    """
    before_change = datetime(2026, 9, 4, 9, 55, tzinfo=BKK)
    after_change = datetime(2026, 9, 4, 9, 0, tzinfo=BKK)

    assert before_change != after_change  # the vendor really did move it
    assert canonical_ts(before_change, "1d") == canonical_ts(after_change, "1d")
    assert canonical_ts(before_change, "1d") == datetime(2026, 9, 4, tzinfo=UTC)


def test_a_third_stamp_lands_on_the_same_key() -> None:
    """The 10:00 BKK stamp also seen in the store must not open a third row."""
    stamps = [
        datetime(2026, 8, 27, 9, 0, tzinfo=BKK),
        datetime(2026, 8, 27, 9, 55, tzinfo=BKK),
        datetime(2026, 8, 27, 10, 0, tzinfo=BKK),
    ]
    keys = {canonical_ts(s, "1d") for s in stamps}
    assert keys == {datetime(2026, 8, 27, tzinfo=UTC)}


def test_session_date_is_the_bangkok_date_not_the_utc_date() -> None:
    """A bar stamped late in the Bangkok evening still belongs to that session.

    02:00Z on 2026-09-05 is 09:00 Bangkok on the 5th, so both the UTC and the
    Bangkok date agree; 17:30Z on the 4th is 00:30 Bangkok on the 5th, where
    they do not. The session calendar is Bangkok's.
    """
    morning_bar = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)
    late_bar = datetime(2026, 9, 4, 17, 30, tzinfo=UTC)
    assert canonical_ts(morning_bar, "1d") == datetime(2026, 9, 5, tzinfo=UTC)
    assert canonical_ts(late_bar, "1d") == datetime(2026, 9, 5, tzinfo=UTC)


@pytest.mark.parametrize("timeframe", ["1h", "5m"])
def test_intraday_bars_keep_their_true_instant(timeframe: str) -> None:
    """Flooring an intraday bar would collapse a whole session onto one key."""
    ts = datetime(2026, 9, 4, 6, 45, tzinfo=UTC)
    assert canonical_ts(ts, timeframe) == ts


def test_naive_timestamp_is_refused() -> None:
    """A naive datetime has no session date — fail loudly rather than guess."""
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_ts(datetime(2026, 9, 4, 9, 0), "1d")  # noqa: DTZ001


def test_result_is_idempotent() -> None:
    """Re-normalising an already-canonical timestamp must not move it."""
    once = canonical_ts(datetime(2026, 9, 4, 9, 55, tzinfo=BKK), "1d")
    assert canonical_ts(once, "1d") == once
