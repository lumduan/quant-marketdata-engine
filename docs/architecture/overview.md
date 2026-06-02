# Architecture — Overview

The Market Data Engine is a standalone `EXTERNAL` engine: **one service fetches market data
and holds the tvkit cookie**, every strategy reads pre-fetched data from one shared store and
never fetches tvkit itself. This page is the system topology; for the storage shape see
[`data-model.md`](data-model.md), for the trust boundary see
[`security-boundary.md`](security-boundary.md).

## Topology

```
        tvkit (premium cookie)  +  settfex (symbol list / actions)
                         │   (owned ONLY by quant-marketdata-engine)
                         ▼
        ┌────────────────────────────────────────────────┐
        │  quant-marketdata-engine   (host :8300 / :8000)  │  EXTERNAL engine
        │   INGEST side: fetch + idempotent upsert         │
        │   READ side:  /health /ohlcv /ohlcv/adjusted     │
        │               /universe  (auth-gated)            │
        │   own Redis sidecar (hot-window cache + lock)    │
        └──────────┬───────────────────────▲─────────────┘
            writes │                        │ reads
                   ▼                        │
        quant-infra-db (TimescaleDB)  ← canonical store (db_market_data)
          market_data.ohlcv             RAW bars; PK (symbol, timeframe, ts)
          market_data.corporate_actions splits / dividends / roll dates
          market_data.ohlcv_adjusted    adjust-on-read VIEW
          market_data.cagg_ohlcv_1h/4h  derived-TF continuous aggregates
          market_data.universe_membership  as-of, point-in-time
                   ▲
                   │  GET /api/v2/engines/market-data/*   (PROXY)
        ┌──────────┴───────────────┐
        │  quant-api-gateway        │  thin reverse proxy · NO tvkit cookie
        └──────────┬───────────────┘
                   ▼
   strategies (csm-set, tfex, …)  +  quant-openbb (v2 proxy panels)
            read — they NEVER fetch tvkit
```

## Two sides of one service

### Ingest side (owner mode only)

Holds `TVKIT_AUTH_TOKEN` (the JSON cookie), fetches bars via tvkit, and **idempotently
upserts** raw OHLCV + corporate actions into `market_data.*`
(`ON CONFLICT (symbol, timeframe, ts) DO UPDATE`). It runs only when
`MARKETDATA_ENGINE_PUBLIC_MODE=false`. Entry points:

- CLI: `uv run python -m src.quant_marketdata_engine.ingest fetch …` (see
  [`../operations/configuration.md`](../operations/configuration.md))
- HTTP: `POST /admin/ingest` (engine-direct, owner mode + API key — see
  [`../api/admin-ingest.md`](../api/admin-ingest.md))

Source: `src/quant_marketdata_engine/ingest/` (`tvkit_client.py`, `service.py`,
`cli.py`, `backfill.py`).

### Read side (private/auth-gated)

Resolves `(symbol, timeframe, range)` and returns the uniform read contract. Source:
`src/quant_marketdata_engine/api/routes.py`. Raw OHLCV is private-side — every read endpoint
is behind `X-API-Key` (see [`security-boundary.md`](security-boundary.md)).

## Read resolution: hot / warm / cold

| Path | Hops | When |
|------|------|------|
| **Hot** | Redis sidecar hit | repeated / latest-bar reads (common case) |
| **Warm** | Redis miss → TimescaleDB hit → write-through to Redis | bar already ingested |
| **Cold** | DB miss/gap → tvkit fetch + upsert → write-through | **only here does anyone call TradingView — always the engine, never a strategy** |

> **Current state:** the read path is **hot/warm only** (Redis → DB → write-through).
> Cold-path auto-fetch-on-read is **deferred** — the single-flight lock primitive is built
> (`cache/single_flight.py`) but ingest is a separate path (CLI / `/admin/ingest`). See
> [`data-flow.md` in `.claude/knowledge`](../../.claude/knowledge/data-flow.md).

Worked example — a strategy reads `SET:PTT` daily bars:

```
strategy ─GET /api/v2/engines/market-data/ohlcv?symbol=SET:PTT&timeframe=1d─▶
  quant-api-gateway (forwards X-API-Key, proxies)
     └─▶ quant-marketdata-engine :8000
            1. Redis hot-window cache ──HIT──▶ return bars
            2. TimescaleDB market_data.ohlcv ──HIT──▶ write-through Redis ▶ return
  strategy gets bars — never touched tvkit
```

## The gateway proxy

`quant-api-gateway` is a **thin reverse proxy** holding no credential. It forwards the read
contract and the caller's `X-API-Key`, and maps upstream failures to clean status codes:

| Proxied path (`/api/v2/engines/market-data/…`) | Upstream (engine `:8000`) |
|---|---|
| `GET /health` | `GET /health` |
| `GET /ohlcv` | `GET /ohlcv` |
| `GET /ohlcv/adjusted` | `GET /ohlcv/adjusted` |
| `GET /universe` | `GET /universe` |

Upstream timeout → `504`; upstream unreachable → `503`; upstream `5xx` / invalid body →
`502`; upstream `4xx` (auth/validation) is forwarded verbatim. `POST /admin/ingest` is **not
proxied** — it is reached on the engine host directly. Source:
`quant-api-gateway/src/api/v2/engines/market_data.py`.

## Design principles (from the ADR, D1–D10)

1. **Store RAW + corporate actions; adjust on read.** Adjusted series change retroactively on
   each new action — never cache an adjusted bar as the source of truth (D2).
2. **One producer owns the credential.** Only this service holds the tvkit cookie (D4/D7).
3. **DB is source of truth; Parquet is a derived cache** for heavy backtest scans (D3).
4. **Point-in-time correctness.** `universe_membership` is as-of dated (D4).
5. **Daily → TimescaleDB.** S50 intraday volume (~152k rows/yr) stays in Timescale; the lake
   is reserved for the ~50M rows/yr threshold (D5).
6. **Futures `1d` close = settlement, never a rollup of intraday** (D10).

Full rationale: [ADR `feature-market-data-engine.md`](../../../.claude/knowledge/feature-market-data-engine.md).
