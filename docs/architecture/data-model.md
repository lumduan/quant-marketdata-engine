# Architecture — Data Model

The canonical store is the **`market_data` schema in the `db_market_data` database**
(TimescaleDB), owned independently of `db_gateway` and the strategy DBs (ADR D4/D7). The SQL
is `quant-infra-db/init-scripts/10_schema_market_data.sql` (+ `11_market_data_caggs.sql`);
this page summarises it. Per-table detail lives under [`../data/`](../data/).

## Tables and objects

| Object | Kind | Purpose |
|--------|------|---------|
| `market_data.ohlcv` | hypertable | RAW bars, one row per `(symbol, timeframe, ts)` |
| `market_data.corporate_actions` | table | splits / dividends (equities) + futures roll dates |
| `market_data.ohlcv_adjusted` | view | adjust-on-read (recomputes on every read) |
| `market_data.cagg_ohlcv_1h` | continuous aggregate | 1h bars derived from the 5m base |
| `market_data.cagg_ohlcv_4h` | continuous aggregate | 4h bars derived from the 5m base |
| `market_data.universe_membership` | table | as-of dated index constituents |

## `market_data.ohlcv` — the base grain

PK `(symbol, timeframe, ts)` (Option A multi-timeframe, D10): the `timeframe` is part of the
key, and bars are **stored as fetched**. Equities, futures (continuous `S501!` + dated
`S50M2026`), and indices all live here, distinguished only by `symbol`.

| Column | Type | Notes |
|--------|------|-------|
| `symbol` | `text` | e.g. `SET:PTT`, `TFEX:S50M2026` |
| `timeframe` | `text` | CHECK ∈ `{'1d','1h','5m'}` |
| `ts` | `timestamptz` | **bar-open** time, stored UTC |
| `open/high/low/close` | `numeric(18,6)` | CHECK `> 0`; CHECK `high >= low` |
| `volume` | `numeric(20,4)` | CHECK `>= 0`, default `0` |
| `open_interest` | `numeric(20,4)` | futures only; **NULL for equities**; carried from day one (D10) |
| `source` | `text` | e.g. `tvkit`, `csm-backfill-div`; default `tvkit` |
| `ingested_at` | `timestamptz` | default `now()` |

- **Hypertable** on `ts`, 30-day chunks.
- **Read index** `idx_ohlcv_symbol_tf_ts` on `(symbol, timeframe, ts DESC)` backs the
  canonical query `WHERE symbol=$1 AND timeframe=$2 [AND ts>=$3] ORDER BY ts DESC`.
- **Compression** after ~7 days, `compress_segmentby = 'symbol, timeframe'`,
  `compress_orderby = 'ts DESC'`. `1d` is tiny and kept forever — **no retention/drop policy**.
- **Idempotent upsert:** `INSERT … ON CONFLICT (symbol, timeframe, ts) DO UPDATE`.

> **Why `numeric(18,6)`** (not the retiring 08/09 tfex mirror's `(18,4)`): this is a shared
> multi-asset store and the ADR §5 read contract serialises 6-dp prices (`"912.400000"`).

## Derived timeframes (continuous aggregates)

`cagg_ohlcv_1h` / `cagg_ohlcv_4h` roll the **5m base** up with TimescaleDB
`time_bucket` (`first(open)`, `max(high)`, `min(low)`, `last(close)`, `sum(volume)`). A new
strategy wanting a new coarse TF costs one CAGG and zero re-fetch, and every reader sees
identical bar boundaries.

**Not derived (by design):**

- Fetched `1d` bars stay authoritative in `ohlcv` and are **never** rolled up from intraday —
  for futures the daily close is the **settlement** price (D10). There is no `1d` CAGG.
- Adjusted/continuous series are the `ohlcv_adjusted` **view**, never a materialised CAGG
  (adjusted series change retroactively).

> **Pending:** the read API serves only `1d | 1h | 5m`. The `cagg_ohlcv_4h` aggregate
> **exists in the DB but is not routed** by the read API, so `4h` reads are declined
> client-side (tfex Phase 4). Enabling a `4h` route is a tracked follow-up.

## Adjust-on-read

`market_data.ohlcv_adjusted` multiplies each bar's prices by a back-adjustment factor: the
cumulative product of `corporate_actions.ratio` over all actions whose `ex_date` is strictly
**after** the bar's date (implemented as `exp(sum(ln(ratio)))` since Postgres has no product
aggregate; `ratio` is constrained `> 0`). Because it is a view, a newly inserted action row
is reflected on the next read — no cache to invalidate. Volume / open_interest pass through
unadjusted. Detail + math: [`../data/corporate-actions.md`](../data/corporate-actions.md).

> **Pending:** the equity split/dividend path is proven; **futures-roll back-adjustment of
> `S501!` is not yet computed engine-side** — tfex back-adjusts locally from raw dated
> contracts (Phase 4). Engine-native roll parity is a Phase 5+ follow-up.

## Numeric precision summary

| Quantity | DB type | Wire (JSON) | Parquet snapshot |
|----------|---------|-------------|------------------|
| open/high/low/close | `numeric(18,6)` | decimal string `"912.400000"` | `decimal128(18,6)` |
| volume | `numeric(20,4)` | decimal string | `decimal128(20,4)` |
| open_interest | `numeric(20,4)` | decimal string or `null` | `decimal128(20,4)` |

See [`../data/parquet-snapshot.md`](../data/parquet-snapshot.md) for the exact Arrow schema.
