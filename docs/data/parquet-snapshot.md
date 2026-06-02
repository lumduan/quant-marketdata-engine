# Data — Parquet Snapshot

The Parquet snapshot is a **derived backtest cache** exported from the DB for heavy offline
historical scans — never a parallel source of truth (D3). The DB is canonical; the snapshot is
materialised from it. Source: `src/quant_marketdata_engine/snapshot/exporter.py`.

## Why it exists

Backtests need fast columnar full-history scans and must stay usable when infra-db is offline.
Streaming millions of rows per run through the API is wasteful, so the engine can export a
`(symbol, timeframe)` series to a columnar Parquet file that backtests read directly.

## Exact Arrow schema (decimal-exact)

Prices are written as **`decimal128`, not float**, preserving the money rule; `ts` is a
microsecond UTC timestamp:

| Field | Arrow type |
|-------|------------|
| `symbol` | `string` |
| `timeframe` | `string` |
| `ts` | `timestamp[us, tz=UTC]` |
| `open` / `high` / `low` / `close` | `decimal128(18, 6)` |
| `volume` | `decimal128(20, 4)` |
| `open_interest` | `decimal128(20, 4)` |
| `source` | `string` |

## Export API

```python
from pathlib import Path
from src.quant_marketdata_engine.snapshot.exporter import export_ohlcv

# raw bars
n = await export_ohlcv(pool, symbol="SET:PTT", timeframe="1d",
                       out_path=Path("snapshots/SET_PTT_1d.parquet"))

# adjust-on-read bars (reads the ohlcv_adjusted view)
n = await export_ohlcv(pool, symbol="SET:PTT", timeframe="1d",
                       out_path=Path("snapshots/SET_PTT_1d_adj.parquet"), adjusted=True)
```

`export_ohlcv(...)` returns the number of bars written, creates parent dirs, and reads the
adjust-on-read view when `adjusted=True` (else the raw base table). Default `limit=100_000`.

## Rules

- **Round-trips with the DB** — the snapshot is regenerated from the canonical store; never
  hand-edit it and never treat it as the source of truth.
- **Decimal-exact** — do not read it as float in a way that loses precision.
- A strategy's own local Parquet (e.g. csm-set `data/raw/`) is likewise a **derived cache**
  post-cutover, materialised from the engine — not an independent fetch.
