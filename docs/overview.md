# Overview

`quant-marketdata-engine` is the platform's **Market Data Engine** — the single canonical
producer of OHLCV and the **sole owner of the TradingView (tvkit) auth cookie**. It is a
FastAPI service (container `:8000`, host `:8300`) on the external `quant-network`, proxied
by `quant-api-gateway` under `/api/v2/engines/market-data/*`. It writes canonical
`market_data.*` tables in `quant-infra-db` (TimescaleDB); strategies **read**, they never
fetch tvkit.

> **Live (Phase 5 in progress, 2026-06-02).** The service is a running FastAPI read API
> (`/health`, `/ohlcv`, `/ohlcv/adjusted`, `/universe`) + owner-mode `/admin/ingest`, with its
> own Redis sidecar and the asyncpg layer over `db_market_data`. The read path is hot/warm
> (Redis → DB → write-through); cold-path auto-fetch is deferred. **Start at the documentation
> hub: [`README.md`](README.md).**

## Where the real documentation lives

| Topic | Document |
|---|---|
| What to build, phase by phase (canonical) | [`plans/ROADMAP.md`](plans/ROADMAP.md) |
| Agent guide, ownership boundaries, conventions | [`../CLAUDE.md`](../CLAUDE.md) |
| Request flow, multi-TF storage, cookie contract, schema touchpoints | [`../.claude/knowledge/market-data-engine.md`](../.claude/knowledge/market-data-engine.md) |
| Dev workflow (bring-up, gates, safe tvkit testing, PR sequence) | [`../.claude/playbooks/development-workflow.md`](../.claude/playbooks/development-workflow.md) |
| Cross-cutting feature design | [`../../plans/feature-market-data-engine/`](../../plans/feature-market-data-engine/) |
| Umbrella system map | [`../../CLAUDE.md`](../../CLAUDE.md) |

## Architecture (one-paragraph)

The **ingest side** (the only holder of `TVKIT_AUTH_TOKEN`) fetches bars via tvkit and
idempotently upserts raw OHLCV + corporate actions / roll dates into TimescaleDB. The
**read side** resolves `(symbol, timeframe, range)` through a hot/warm path (own Redis
sidecar → TimescaleDB → write-through; cold-path on-miss ingest is deferred), applies
adjust-on-read for adjusted/continuous
series, and returns a uniform contract through the gateway. A Parquet snapshot exporter
materialises the DB for offline backtest scans. See [`plans/ROADMAP.md`](plans/ROADMAP.md)
for the phase-by-phase build.
