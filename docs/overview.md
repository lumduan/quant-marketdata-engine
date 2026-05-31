# Overview

`quant-marketdata-engine` is the platform's **Market Data Engine** — the single canonical
producer of OHLCV and the **sole owner of the TradingView (tvkit) auth cookie**. It is a
FastAPI service (container `:8000`, host `:8300`) on the external `quant-network`, proxied
by `quant-api-gateway` under `/api/v2/engines/market-data/*`. It writes canonical
`market_data.*` tables in `quant-infra-db` (TimescaleDB); strategies **read**, they never
fetch tvkit.

> **Scaffold only.** No fetch / storage / read-API / Redis logic exists yet — that is the
> Phase 2+ build target, gated on the Phase 0 ADR.

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
**read side** resolves `(symbol, timeframe, range)` through a hot/warm/cold path (own Redis
sidecar → TimescaleDB → on-miss ingest), applies adjust-on-read for adjusted/continuous
series, and returns a uniform contract through the gateway. A Parquet snapshot exporter
materialises the DB for offline backtest scans. See [`plans/ROADMAP.md`](plans/ROADMAP.md)
for the phase-by-phase build.
