# quant-marketdata-engine — Documentation

The **Market Data Engine** is the single canonical producer of OHLCV for the quant platform
and the **sole owner of the TradingView (tvkit) auth cookie**. It is a FastAPI service
(container `:8000`, host `:8300`) on the external `quant-network`, proxied by
`quant-api-gateway` under `/api/v2/engines/market-data/*`. It writes the canonical
`market_data.*` tables in `quant-infra-db` (TimescaleDB) and ships its own Redis sidecar.
Strategies **read**; they never fetch tvkit.

> **State (2026-06-02):** live — Phases 2–4 shipped, Phase 5 partial (csm-set cut over &
> verified; tfex pending), Phase 6 documentation (this hierarchy) in progress. See
> [`plans/ROADMAP.md`](plans/ROADMAP.md).

This page is the **documentation hub** — start here and follow the links.

## Architecture

| Doc | What it covers |
|-----|----------------|
| [`architecture/overview.md`](architecture/overview.md) | Service topology, ingest vs read sides, hot/warm resolution, gateway-proxy position, the cookie-owner invariant |
| [`architecture/data-model.md`](architecture/data-model.md) | `market_data.*` schema, PK `(symbol, timeframe, ts)`, continuous aggregates, compression, numeric precision |
| [`architecture/security-boundary.md`](architecture/security-boundary.md) | `X-API-Key` auth gate, sole-cookie-owner model, the public-data boundary, public vs owner mode |

## API reference

| Doc | Endpoint |
|-----|----------|
| [`api/health.md`](api/health.md) | `GET /health` — readiness (DB / Redis / cookie presence) |
| [`api/ohlcv.md`](api/ohlcv.md) | `GET /ohlcv` — raw bars |
| [`api/ohlcv-adjusted.md`](api/ohlcv-adjusted.md) | `GET /ohlcv/adjusted` — adjust-on-read bars |
| [`api/universe.md`](api/universe.md) | `GET /universe` — as-of dated index constituents |
| [`api/admin-ingest.md`](api/admin-ingest.md) | `POST /admin/ingest` — owner-mode tvkit ingest (engine-direct) |

All read endpoints are gateway-proxied under `/api/v2/engines/market-data/*`; `/admin/ingest`
is **engine-direct, owner-mode only** (never proxied).

## Operations

| Doc | What it covers |
|-----|----------------|
| [`operations/bring-up.md`](operations/bring-up.md) | Bring-up order, compose files (public vs owner overlay), network prerequisite, health checks |
| [`operations/configuration.md`](operations/configuration.md) | Every `MARKETDATA_ENGINE_*` env var + `TVKIT_AUTH_TOKEN`; the strategy reader flags; safe cookie injection |
| [`operations/troubleshooting.md`](operations/troubleshooting.md) | Cookie expiry, DB/Redis down, gateway 502/503/504, public-mode ingest refusal |

## Data model

| Doc | What it covers |
|-----|----------------|
| [`data/ohlcv-schema.md`](data/ohlcv-schema.md) | OHLCV hypertable: columns, constraints, compression, idempotent upsert |
| [`data/corporate-actions.md`](data/corporate-actions.md) | Splits / dividends / futures roll dates; adjust-on-read math |
| [`data/universe-membership.md`](data/universe-membership.md) | As-of dated constituents, point-in-time correctness |
| [`data/parquet-snapshot.md`](data/parquet-snapshot.md) | DB → Parquet derived backtest cache (decimal-exact) |

## Plans (build history)

The phase-by-phase build lives under [`plans/`](plans/) — [`plans/ROADMAP.md`](plans/ROADMAP.md)
is canonical. Phase 6 (this docs work) is [`plans/phase6-documentation.md`](plans/phase6-documentation.md).

## Conventions used throughout these docs

- **Money is `Decimal`, serialised as a string on the wire** (e.g. `"912.400000"`), never
  `float`. Prices are `numeric(18,6)`; volume / open_interest `numeric(20,4)`.
- **Timestamps are UTC** (`ts` = bar-open time); display in `Asia/Bangkok` at the edge.
- **Secrets are placeholders.** The tvkit cookie (`TVKIT_AUTH_TOKEN`) and API keys never
  appear with real values; examples use `<...>` placeholders.
- **In-container hostnames** (`quant-marketdata-engine`, `quant-postgres`, `marketdata-redis`)
  are used inside `quant-network`; host ports (`:8300`, etc.) are for developer access only.

## Cross-repo references

| Resource | Path |
|----------|------|
| Engine agent guide | [`../CLAUDE.md`](../CLAUDE.md) |
| Umbrella system map + engine catalog | [`../../CLAUDE.md`](../../CLAUDE.md) |
| Umbrella feature roadmap | [`../../plans/feature-market-data-engine/ROADMAP.md`](../../plans/feature-market-data-engine/ROADMAP.md) |
| ADR (D1–D10, read contract) | [`../../.claude/knowledge/feature-market-data-engine.md`](../../.claude/knowledge/feature-market-data-engine.md) |
| Cutover runbook | [`../../.claude/playbooks/marketdata-engine-cutover.md`](../../.claude/playbooks/marketdata-engine-cutover.md) |
| Canonical schema (SQL) | `quant-infra-db/init-scripts/10_schema_market_data.sql`, `11_market_data_caggs.sql` |
| Gateway proxy route | `quant-api-gateway/src/api/v2/engines/market_data.py` |
