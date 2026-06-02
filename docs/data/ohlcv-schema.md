# Data — OHLCV Schema

The canonical bar store: `market_data.ohlcv`, a TimescaleDB hypertable in the
`db_market_data` database. Defined in
`quant-infra-db/init-scripts/10_schema_market_data.sql`. The engine is the sole writer
(Phase 2); strategies read via the API. Architectural context:
[`../architecture/data-model.md`](../architecture/data-model.md).

## Columns

| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| `symbol` | `text` | PK | `SET:PTT`, `TFEX:S50M2026`, indices — all distinguished by symbol |
| `timeframe` | `text` | PK, CHECK ∈ `{1d,1h,5m}` | bar grain |
| `ts` | `timestamptz` | PK | **bar-open** time, stored UTC |
| `open` | `numeric(18,6)` | CHECK `> 0` | |
| `high` | `numeric(18,6)` | CHECK `> 0`, CHECK `high >= low` | |
| `low` | `numeric(18,6)` | CHECK `> 0` | |
| `close` | `numeric(18,6)` | CHECK `> 0` | futures `1d` close = **settlement** |
| `volume` | `numeric(20,4)` | CHECK `>= 0`, default `0` | |
| `open_interest` | `numeric(20,4)` | CHECK NULL or `>= 0` | futures only; **NULL for equities** |
| `source` | `text` | default `tvkit` | e.g. `tvkit`, `csm-backfill-div` |
| `ingested_at` | `timestamptz` | default `now()` | |

**Primary key:** `(symbol, timeframe, ts)` — Option A multi-timeframe (D10). The natural key
makes every write idempotent.

## Hypertable, index, compression

```sql
SELECT create_hypertable('market_data.ohlcv', 'ts', chunk_time_interval => INTERVAL '30 days');

CREATE INDEX idx_ohlcv_symbol_tf_ts ON market_data.ohlcv (symbol, timeframe, ts DESC);

ALTER TABLE market_data.ohlcv SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'symbol, timeframe',
  timescaledb.compress_orderby   = 'ts DESC'
);
SELECT add_compression_policy('market_data.ohlcv', INTERVAL '7 days');
```

- 30-day chunks; closed chunks compress after ~7 days.
- `1d` data is tiny and kept forever — **no retention/drop policy** (D9).
- The index backs the canonical read:
  `WHERE symbol=$1 AND timeframe=$2 [AND ts>=$3] ORDER BY ts DESC`.

## Idempotent upsert contract

Re-running an ingest is safe — unchanged bars are no-ops, late corrections overwrite:

```sql
INSERT INTO market_data.ohlcv (symbol, timeframe, ts, open, high, low, close, volume, open_interest, source)
VALUES (...)
ON CONFLICT (symbol, timeframe, ts) DO UPDATE
  SET open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
      close = EXCLUDED.close, volume = EXCLUDED.volume,
      open_interest = EXCLUDED.open_interest, source = EXCLUDED.source,
      ingested_at = now();
```

## Rules

- **Store RAW/unadjusted** bars; adjustment is a read-time view
  ([`corporate-actions.md`](corporate-actions.md)).
- **Futures `1d` = settlement**, never a rollup of intraday (D10). Coarser intraday TFs a
  strategy did not fetch are derived via continuous aggregates (`cagg_ohlcv_1h/4h`) — never the
  `1d` settlement bar.
- **Money is `Decimal`** (`numeric` in DB, decimal string on the wire), never `float`.
